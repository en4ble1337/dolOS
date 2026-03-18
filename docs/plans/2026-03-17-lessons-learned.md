# Lessons Learned & Behavioral Reinforcement

**Supersedes:** `docs/plans/2026-03-16-lessons-learned.md` (corrected variable names and heartbeat wiring to match current codebase)

The agent learns from its own mistakes. After each conversation turn the `LessonExtractor` looks for corrections or preference signals and appends them to `data/LESSONS.md`. The agent reads that file on every turn and injects it into its system prompt, so lessons immediately affect behaviour. Periodically the `ReflectionTask` (a heartbeat integration) consolidates the file when it grows too large.

---

## Architecture at a Glance

```
User correction detected
        │
        ▼
LessonExtractor.extract_and_store()  ← background task after each turn
        │
        ├── LLM prompt → JSON [{"title","context","lesson"}]
        ├── Dedup via MemoryManager semantic search (threshold 0.90)
        ├── Append to data/LESSONS.md
        └── Store in semantic memory (source: "lesson")
                                          │
                                          ▼
                              Agent reads LESSONS.md on every turn
                              → injects <lessons_learned> block into system prompt

data/LESSONS.md grows past 20 entries
        │
        ▼
ReflectionTask.check()  ← heartbeat integration, every 5 min
        │
        └── LLM consolidation → rewrites LESSONS.md (merged, deduplicated)
```

---

## Changes Required

### 1. [MODIFY] `core/telemetry.py`

Add event types (mirrors the `SEMANTIC_*` pattern already in the file):

```python
# Lesson Extraction
LESSON_EXTRACTION_START = "memory.lesson.extraction.start"
LESSON_EXTRACTION_COMPLETE = "memory.lesson.extraction.complete"
LESSON_EXTRACTION_ERROR = "memory.lesson.extraction.error"
LESSON_DUPLICATE_SKIPPED = "memory.lesson.duplicate"

# Reflection (heartbeat consolidation)
REFLECTION_START = "heartbeat.reflection.start"
REFLECTION_COMPLETE = "heartbeat.reflection.complete"
REFLECTION_ERROR = "heartbeat.reflection.error"
```

---

### 2. `data/LESSONS.md` Schema

Auto-managed file. Created by `LessonExtractor` on first lesson. Format:

```markdown
# Agent Lessons Learned

<!-- This file is auto-managed. Do not edit manually. -->

## [YYYY-MM-DD] Lesson title or short summary
**Context:** What the agent did wrong or what was discovered.
**Lesson:** The correct behaviour or approach going forward.

---
```

- Each lesson is a `## [DATE] title` block.
- Two fields: `**Context:**` and `**Lesson:**`.
- Entries separated by `---`.
- `LessonExtractor` appends; `ReflectionTask` rewrites after consolidation.
- Consolidation triggers at 20 entries (configurable).

---

### 3. [NEW] `memory/lesson_extractor.py`

Mirrors `SemanticExtractor` in structure.

**LLM extraction prompt:**
```
Analyse this conversation exchange. Identify any of the following signals:
1. The user explicitly corrected the assistant.
2. The assistant made a mistake and then recovered.
3. A better approach or method was discovered.
4. The user stated a preference about HOW the assistant should work.

Return ONLY a JSON array: [{"title": "...", "context": "...", "lesson": "..."}]
If none apply, return [].

User: {user_message}
Assistant: {assistant_response}
```

**Deduplication:** Semantic search against `"semantic"` collection (tag `source: "lesson"`) with threshold 0.90. Skips if a near-identical lesson already exists.

**Storage (two-step):**
1. Append structured entry to `data/LESSONS.md`.
2. Store in semantic memory with `metadata={"source": "lesson"}`.

**Bootstrap:** `_append_to_file` creates `data/LESSONS.md` with the header template if the file does not exist. `os.makedirs("data", exist_ok=True)` ensures the directory exists.

**Interface:**

```python
class LessonExtractor:
    def __init__(
        self,
        llm: LLMGateway,
        memory: MemoryManager,
        lessons_path: str = "data/LESSONS.md",
        event_bus: Optional[EventBus] = None,
        similarity_threshold: float = 0.90,
    ) -> None: ...

    async def extract_and_store(
        self,
        user_message: str,
        assistant_response: str,
        session_id: str,
        trace_id: str,
    ) -> int:
        """Returns count of new lessons stored."""
        ...

    async def _is_duplicate(self, lesson_text: str) -> bool:
        """Check semantic memory for a near-identical lesson."""
        ...

    def _append_to_file(self, lessons: list[dict]) -> None:
        """Create data/ dir and file if needed; append structured entries."""
        ...
```

Note: `_is_duplicate` is `async` because `MemoryManager.search` may be async.

---

### 4. [MODIFY] `core/agent.py`

**Constructor — add `lesson_extractor` parameter:**

```python
def __init__(
    self,
    llm: LLMGateway,
    memory: MemoryManager,
    event_bus: Optional[EventBus] = None,
    skill_executor: Optional[SkillExecutor] = None,
    semantic_extractor: Optional["SemanticExtractor"] = None,
    summarizer: Optional["ConversationSummarizer"] = None,
    lesson_extractor: Optional["LessonExtractor"] = None,  # NEW
) -> None:
```

**System prompt injection** — insert between `<soul_instructions>` and `summary_context`:

```python
lessons_path = "data/LESSONS.md"
lessons_content = ""
if os.path.exists(lessons_path):
    with open(lessons_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if raw:
        lessons_content = (
            "Here are behavioural lessons learned from past mistakes — follow these strictly:\n\n"
            f"<lessons_learned>\n{raw}\n</lessons_learned>\n\n"
        )
```

Full system prompt order:
1. `<soul_instructions>`
2. `<lessons_learned>` ← NEW (only if file is non-empty)
3. Previous conversation summary (if any)
4. Episodic memory
5. Semantic memory
6. CRITICAL INSTRUCTION footer

**Background task** — add to `_schedule_background_tasks`:

```python
if self.lesson_extractor:
    asyncio.create_task(
        self._run_lesson_extraction(session_id, message, content, trace_id)
    )
```

**New runner method:**

```python
async def _run_lesson_extraction(
    self, session_id: str, user_message: str, assistant_response: str, trace_id: str
) -> None:
    try:
        await self.lesson_extractor.extract_and_store(  # type: ignore[union-attr]
            user_message=user_message,
            assistant_response=assistant_response,
            session_id=session_id,
            trace_id=trace_id,
        )
    except Exception as e:
        logger.warning("Lesson extraction failed: %s", e)
```

---

### 5. [NEW] `heartbeat/integrations/reflection_task.py`

Extends `HeartbeatIntegration`. Triggered by the heartbeat scheduler every 5 minutes.

**Trigger logic:** Count-based. `check()`:
1. Reads `data/LESSONS.md` and counts lesson entries (`## [` headers).
2. If count < `consolidation_threshold` → returns `{"status": "skipped", "lesson_count": N}`.
3. If count >= threshold → calls LLM to consolidate, rewrites file.

**Consolidation LLM prompt:**
```
You are reviewing a list of lessons learned by an AI agent.
Consolidate these lessons by:
1. Merging lessons that cover the same topic.
2. Removing lessons that have become redundant.
3. Keeping the most specific and actionable phrasing.

Return the result as a valid LESSONS.md file using the exact same format.

Current lessons:
{current_content}
```

**Interface:**

```python
class ReflectionTask(HeartbeatIntegration):
    name: str = "reflection_task"

    def __init__(
        self,
        llm: LLMGateway,
        event_bus: EventBus,
        lessons_path: str = "data/LESSONS.md",
        consolidation_threshold: int = 20,
    ) -> None: ...

    async def check(self) -> dict[str, Any]: ...
    def _count_lessons(self, content: str) -> int: ...
    async def _consolidate(self, content: str, trace_id: str) -> str: ...
```

`_count_lessons` counts `## [` occurrences in the file content.

`ReflectionTask` does **not** use `MemoryManager` — it only reads/writes `LESSONS.md`. Semantic memory entries tagged `source: "lesson"` are not cleaned up (they only serve as dedup lookup keys for `LessonExtractor`).

---

### 6. [MODIFY] `memory/__init__.py`

Add `LessonExtractor` alongside existing exports:

```python
from memory.lesson_extractor import LessonExtractor

__all__ = [
    "VectorStore",
    "EmbeddingService",
    "MemoryManager",
    "SemanticExtractor",
    "ConversationSummarizer",
    "LessonExtractor",  # NEW
]
```

---

### 7. [MODIFY] `main.py`

**Imports to add:**

```python
from heartbeat.integrations.reflection_task import ReflectionTask
from memory.lesson_extractor import LessonExtractor
```

**New component instantiation** (after `summarizer` block, before `agent`):

```python
lesson_extractor = LessonExtractor(
    llm=llm,
    memory=memory,
    event_bus=event_bus,
) if settings.lesson_extraction_enabled else None
```

**Update `Agent(...)` constructor call:**

```python
agent = Agent(
    llm=llm,
    memory=memory,
    event_bus=event_bus,
    semantic_extractor=semantic_extractor,
    summarizer=summarizer,
    lesson_extractor=lesson_extractor,  # NEW
)
```

**Wire `ReflectionTask` into heartbeat** (in `lifespan`, after `register_default_tasks`):

```python
reflection_task = ReflectionTask(llm=llm, event_bus=event_bus)
heartbeat.register_integration(reflection_task)
```

Note: `register_integration()` is the correct method (added in the infrastructure-gaps work). Do NOT use the old stub pattern.

---

### 8. [MODIFY] `core/config.py`

```python
lesson_extraction_enabled: bool = Field(default=True)
lesson_consolidation_threshold: int = Field(default=20)
```

Pass `consolidation_threshold=settings.lesson_consolidation_threshold` to `ReflectionTask` in `main.py`.

---

## TDD Implementation Order

Follow the TDD Iron Law: failing test first, then production code.

### Phase 1: Telemetry (no tests needed — pure enum extension)
- Add `LESSON_*` and `REFLECTION_*` event types to `core/telemetry.py`.

### Phase 2: `LessonExtractor`
1. Write `tests/memory/test_lesson_extractor.py` (see tests below). Run → red.
2. Implement `memory/lesson_extractor.py`.
3. Run → green.

### Phase 3: `Agent` integration
1. Write `tests/core/test_agent_learning.py` (see tests below). Run → red.
2. Modify `core/agent.py` (constructor + prompt injection + background task).
3. Run → green.

### Phase 4: `ReflectionTask`
1. Write `tests/heartbeat/test_reflection_task.py` (see tests below). Run → red.
2. Implement `heartbeat/integrations/reflection_task.py`.
3. Run → green.

### Phase 5: Wiring
- Update `memory/__init__.py`.
- Update `core/config.py`.
- Update `main.py`.
- Run full test suite.

---

## Test Specifications

### `tests/memory/test_lesson_extractor.py`

- `test_lesson_extracted_from_correction`: LLM returns a correction → file appended, semantic memory written, returns 1.
- `test_no_lesson_when_llm_returns_empty`: LLM returns `[]` → no file write, returns 0.
- `test_deduplication_skips_similar_lesson`: semantic search returns high-similarity hit → lesson skipped, returns 0.
- `test_file_created_if_not_exists`: first lesson → `data/LESSONS.md` created with header + entry.
- `test_malformed_json_is_parsed`: LLM returns markdown-fenced JSON → parsed correctly.
- `test_llm_failure_emits_error_event`: LLM raises → `LESSON_EXTRACTION_ERROR` event emitted.
- `test_telemetry_events_emitted`: successful extraction → `LESSON_EXTRACTION_START` and `LESSON_EXTRACTION_COMPLETE` emitted.
- `test_empty_messages_skipped`: blank user message → early return, 0 stored.

### `tests/core/test_agent_learning.py`

- `test_lessons_injected_into_system_prompt`: `LESSONS.md` exists with content → `<lessons_learned>` block in system prompt passed to LLM.
- `test_lessons_not_injected_when_file_missing`: no `LESSONS.md` → no `<lessons_learned>` block.
- `test_lessons_not_injected_when_file_empty`: file exists but is empty → no injection.
- `test_lesson_extraction_scheduled_as_background_task`: after `process_message`, `lesson_extractor.extract_and_store` is called.
- `test_lesson_extractor_optional`: `lesson_extractor=None` → agent works normally without error.

### `tests/heartbeat/test_reflection_task.py`

- `test_skips_consolidation_below_threshold`: 5 lessons, threshold 20 → returns `{"status": "skipped", "lesson_count": 5}`.
- `test_triggers_consolidation_at_threshold`: 25 lessons, threshold 20 → LLM called, file rewritten.
- `test_file_not_found_returns_skipped`: `LESSONS.md` missing → `{"status": "skipped", "lesson_count": 0}`, no crash.
- `test_telemetry_events_emitted`: consolidation triggered → `REFLECTION_START` and `REFLECTION_COMPLETE` emitted.
- `test_llm_failure_is_propagated`: LLM raises → error propagated, original file unchanged.
- `test_count_lessons_empty_file`: empty string → 0.
- `test_count_lessons_counts_headers`: content with 3 `## [` headers → 3.

---

## Verification

### Manual test
1. Boot the agent.
2. Ask it to do something, then correct it: "No, you should always do X instead of Y."
3. Check `data/LESSONS.md` — new entry should appear within seconds.
4. Start a new session. Confirm the system prompt (via `LOG_LEVEL=DEBUG`) contains `<lessons_learned>`.
5. After 20+ lessons, check `journalctl -u dolOS` for `REFLECTION_COMPLETE` event.
