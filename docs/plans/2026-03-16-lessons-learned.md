# Lessons Learned & Behavioral Reinforcement

Add a mechanism for the agent to identify mistakes, capture "Lessons Learned," and store them in a persistent file (`data/LESSONS.md`) which is injected into the system prompt to prevent repeating errors.

---

## Gaps in the Original Plan (Analysis)

The original plan had the right idea but was missing critical implementation details. The gaps identified:

1. No `EventType` additions to `core/telemetry.py` — every other async background component has dedicated event types.
2. `LESSONS.md` format was undefined — LessonExtractor writes it, agent.py reads it, ReflectionTask consolidates it: all three need the same schema.
3. No deduplication strategy — `SemanticExtractor` uses vector similarity; lessons need an equivalent.
4. `ReflectionTask` referenced non-existent `memory/YYYY-MM-DD.md` log files. The memory system is vector-based; the task must read from `LESSONS.md` directly.
5. `Agent.__init__` constructor change not specified.
6. No decision on where lessons are injected in the system prompt.
7. `main.py` wiring not mentioned.
8. `data/LESSONS.md` file creation/bootstrapping not addressed.
9. `ReflectionTask` trigger condition was vague ("daily or every few hours").
10. `memory/__init__.py` export update not mentioned.
11. Missing test cases: `ReflectionTask`, file-not-found graceful handling, empty-file handling.
12. No lesson count/size limit triggering consolidation.

---

## Proposed Changes

### 1. [MODIFY] `core/telemetry.py`

Add new `EventType` entries for the lesson extraction pipeline (mirroring the `SEMANTIC_*` pattern):

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

### 2. [NEW] `data/LESSONS.md` — Schema Definition

The file uses a structured Markdown format so it can be parsed programmatically by `ReflectionTask` and injected verbatim into the system prompt.

```markdown
# Agent Lessons Learned

<!-- This file is auto-managed. Do not edit manually. -->

## [YYYY-MM-DD] Lesson title or short summary
**Context:** What the agent did wrong or what was discovered.
**Lesson:** The correct behavior or approach to use going forward.

---
```

- Each lesson is a `## [DATE] title` block.
- Two fields: `**Context:**` and `**Lesson:**`.
- Entries are separated by `---`.
- The `LessonExtractor` appends new entries; `ReflectionTask` rewrites the file after consolidation.
- Maximum 50 lesson entries before consolidation is triggered.

---

### 3. [NEW] `memory/lesson_extractor.py`

Mirrors `SemanticExtractor` in structure. Key design decisions:

**LLM Prompt:** Focused on corrections and mistakes, not general facts:

```
Analyze this conversation exchange. Identify any of the following signals:
1. The user explicitly corrected the assistant.
2. The assistant made a mistake and then recovered.
3. A better approach or method was discovered.
4. The user stated a preference about HOW the assistant should work.

Return ONLY a JSON array of objects: [{"title": "...", "context": "...", "lesson": "..."}]
If none apply, return [].

User: {user_message}
Assistant: {assistant_response}
```

**Deduplication:** Use the existing `MemoryManager` semantic search to check if a near-identical lesson already exists in the `"semantic"` collection (tagged with `source: "lesson"`). Use a similarity threshold of `0.90`. This avoids storing duplicate lessons without a separate vector collection.

**Storage:** Two-step:
1. Append the structured entry to `data/LESSONS.md` (file I/O).
2. Also store as a semantic memory with `metadata={"source": "lesson"}` to enable deduplication lookups.

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

    def _is_duplicate(self, lesson_text: str) -> bool:
        """Check semantic memory for near-identical lesson."""
        ...

    def _append_to_file(self, lessons: list[dict]) -> None:
        """Create data/ dir and file if needed; append structured entries."""
        ...
```

**Bootstrap:** `_append_to_file` creates `data/LESSONS.md` with the header template if it doesn't exist. The `data/` directory is created with `os.makedirs("data", exist_ok=True)`.

---

### 4. [MODIFY] `core/agent.py`

**Constructor change:**

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

**System prompt injection:** Lessons are injected between the `<soul_instructions>` block and the episodic memory block, so behavioral rules appear before context:

```python
lessons_content = ""
if os.path.exists(lessons_path):
    with open(lessons_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if raw:
        lessons_content = (
            "Here are behavioral lessons learned from past mistakes — follow these strictly:\n\n"
            f"<lessons_learned>\n{raw}\n</lessons_learned>\n\n"
        )
```

The full prompt order becomes:
1. `<soul_instructions>`
2. `<lessons_learned>` (NEW — only if non-empty)
3. Previous conversation summary (if any)
4. Episodic memory
5. Semantic memory
6. CRITICAL INSTRUCTION footer

**Background task:** Add `LessonExtractor` to `_schedule_background_tasks`, mirroring the `SemanticExtractor` pattern exactly:

```python
if self.lesson_extractor:
    asyncio.create_task(
        self._run_lesson_extraction(session_id, message, content, trace_id)
    )
```

---

### 5. [NEW] `heartbeat/integrations/reflection_task.py`

Extends `HeartbeatIntegration`. Triggered by the heartbeat scheduler.

**Trigger condition:** Count-based, not purely time-based. The `check()` method:
1. Reads `data/LESSONS.md` and counts lesson entries.
2. If count >= `consolidation_threshold` (default: 20), triggers consolidation.
3. Returns immediately with `{"status": "skipped", "lesson_count": N}` if below threshold.

**Consolidation logic:**
1. Read all lesson entries from `LESSONS.md`.
2. Call the LLM with a consolidation prompt to merge similar lessons and remove redundancies.
3. Write the consolidated result back to `LESSONS.md` (full rewrite, not append).
4. Log a `REFLECTION_COMPLETE` event with before/after counts.

**Consolidation prompt:**
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

**Note:** `ReflectionTask` does **not** use `MemoryManager` — it only reads/writes `LESSONS.md` directly. The semantic memory entries tagged `source: "lesson"` are not cleaned up (they serve only as dedup lookups for `LessonExtractor`).

---

### 6. [MODIFY] `memory/__init__.py`

Export `LessonExtractor` from the package alongside `SemanticExtractor` and `ConversationSummarizer`.

---

### 7. [MODIFY] `main.py`

Wire the new components at startup:

```python
lesson_extractor = LessonExtractor(
    llm=llm_gateway,
    memory=memory_manager,
    event_bus=event_bus,
)

agent = Agent(
    llm=llm_gateway,
    memory=memory_manager,
    event_bus=event_bus,
    skill_executor=skill_executor,
    semantic_extractor=semantic_extractor,
    summarizer=summarizer,
    lesson_extractor=lesson_extractor,  # NEW
)

# Register reflection task with the heartbeat scheduler
integration_registry.register(
    ReflectionTask(llm=llm_gateway, event_bus=event_bus)
)
```

---

## TDD Implementation Order

Follow the **TDD Iron Law**: failing test first, then production code.

### Phase 1: Telemetry (no tests needed — pure enum extension)
- Add `LESSON_*` and `REFLECTION_*` event types to `core/telemetry.py`.

### Phase 2: `LessonExtractor` (test-first)
1. Write `tests/memory/test_lesson_extractor.py` with all cases (see below).
2. Run — all tests fail (red).
3. Implement `memory/lesson_extractor.py`.
4. Run — all tests pass (green).

### Phase 3: `Agent` integration (test-first)
1. Write `tests/core/test_agent_learning.py` with injection and background task cases (see below).
2. Run — tests fail (red).
3. Modify `core/agent.py`.
4. Run — tests pass (green).

### Phase 4: `ReflectionTask` (test-first)
1. Write `tests/heartbeat/test_reflection_task.py` (see below).
2. Run — tests fail (red).
3. Implement `heartbeat/integrations/reflection_task.py`.
4. Run — tests pass (green).

### Phase 5: Wiring
- Update `memory/__init__.py`.
- Update `main.py`.
- Run full test suite.

---

## Verification Plan

### Automated Tests

#### `tests/memory/test_lesson_extractor.py`
- `test_lesson_extracted_from_correction`: LLM returns a correction → file appended, semantic memory written.
- `test_no_lesson_when_llm_returns_empty`: LLM returns `[]` → no file write, 0 stored.
- `test_deduplication_skips_similar_lesson`: Semantic search returns high-similarity result → lesson skipped.
- `test_file_created_if_not_exists`: First lesson → `data/LESSONS.md` created with header + entry.
- `test_malformed_json_fallback`: LLM returns markdown-fenced JSON → parsed correctly.
- `test_llm_failure_propagates_with_telemetry`: LLM raises → `LESSON_EXTRACTION_ERROR` event emitted.
- `test_telemetry_events_emitted`: Successful extraction → `START` and `COMPLETE` events emitted.
- `test_empty_messages_skipped`: Blank messages → early return, 0 stored.

#### `tests/core/test_agent_learning.py`
- `test_lessons_injected_into_system_prompt`: `LESSONS.md` exists with content → `<lessons_learned>` block appears in system prompt.
- `test_lessons_not_injected_when_file_missing`: No `LESSONS.md` → system prompt has no `<lessons_learned>` block.
- `test_lessons_not_injected_when_file_empty`: `LESSONS.md` exists but is empty → no injection.
- `test_lesson_extraction_scheduled_as_background_task`: After `process_message`, `lesson_extractor.extract_and_store` is called.
- `test_lesson_extractor_optional`: `lesson_extractor=None` → `Agent` works normally without error.

#### `tests/heartbeat/test_reflection_task.py`
- `test_skips_consolidation_below_threshold`: 5 lessons, threshold 20 → returns `status: skipped`.
- `test_triggers_consolidation_at_threshold`: 25 lessons, threshold 20 → LLM consolidation called, file rewritten.
- `test_file_not_found_returns_healthy`: `LESSONS.md` missing → returns `status: skipped`, no crash.
- `test_telemetry_events_emitted`: Consolidation triggered → `REFLECTION_START` and `REFLECTION_COMPLETE` emitted.
- `test_consolidation_llm_failure_propagates`: LLM raises → error propagated, original file unchanged.

### Manual Verification
1. Run the agent and intentionally make it do something wrong (e.g., give a bad format answer).
2. Correct it: "No, you should always do X instead of Y."
3. Check that `data/LESSONS.md` has a new entry within seconds of the response.
4. Start a new session and confirm the agent applies the lesson (observe the system prompt via debug logging).
5. After 20+ lessons, trigger the heartbeat manually and verify `LESSONS.md` is consolidated.
