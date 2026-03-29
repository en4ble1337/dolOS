# Memory System: Comprehensive Improvement Plan

**Date:** 2026-03-28
**Scope:** `memory/`, `core/agent.py`, `data/`
**Priority order:** High → Medium → Low

---

## Current Architecture (Baseline)

Per turn, the agent executes this pipeline:

```
User message
  → [Write] episodic: "User: {message}"
  → [Search] episodic top-5 + semantic top-3 (weighted score)
  → [Build prompt] SOUL.md (full file) + LESSONS.md (full file) + search results
  → [LLM call]
  → [Write] episodic: "Assistant: {response}"
  → [Background] SemanticExtractor → extract durable facts → semantic collection
  → [Background] LessonExtractor → extract corrections/preferences → semantic + LESSONS.md
  → [Background] ConversationSummarizer → every 10 turns → compress session
```

**Static context loaded from disk each turn:**
- `data/SOUL.md` — always loaded in full
- `data/LESSONS.md` — loaded in full if it exists

**Never loaded at runtime:**
- `data/USER.md` — user profile, timezone, preferences, active hours
- `data/MEMORY.md` — architecture decisions, technical learnings

---

## Gap 1 (HIGH): USER.md and MEMORY.md Are Never Injected

### Problem
`agent.py:110-124` only reads `SOUL.md` and `LESSONS.md`. `USER.md` and `MEMORY.md` are maintained as reference docs but the agent never sees them. This means:
- The agent has no awareness of the user's timezone, active hours, or communication preferences.
- Architecture decisions recorded in `MEMORY.md` are invisible to the agent at runtime.

### Root Cause
The static file loading in `agent.py` was never extended beyond SOUL + LESSONS.

### Recommendation
Index `USER.md` and `MEMORY.md` into the **semantic** Qdrant collection at startup (one-time chunked ingestion), then retrieve relevant chunks via vector search rather than injecting the full files wholesale.

**Implementation steps:**

1. Add `memory/static_loader.py`:

```python
class StaticFileLoader:
    """Indexes static Markdown files into semantic memory at boot.
    Skips files that are already indexed (checks by source path + mtime).
    """
    def __init__(self, memory: MemoryManager, chunk_size: int = 400, overlap: int = 80) -> None: ...

    def index_file(self, path: str, source_tag: str) -> int:
        """Chunk file into overlapping windows and upsert to semantic memory.
        Returns number of chunks stored."""
        ...
```

2. Call at startup in `main.py` (after `MemoryManager` is built):
```python
loader = StaticFileLoader(memory)
loader.index_file("data/USER.md", source_tag="user_profile")
loader.index_file("data/MEMORY.md", source_tag="long_term_decisions")
```

3. The existing `semantic_results = memory.search(query=message, memory_type="semantic", limit=3)` in `agent.py` will automatically surface relevant USER.md/MEMORY.md chunks alongside extracted facts — no agent.py changes needed.

**Why chunking over full injection:**
- `MEMORY.md` is ~200 lines and growing. Injecting it wholesale adds ~3,000 tokens to every prompt.
- Chunking + vector search means only the 2-3 most relevant sections surface per query (~300 tokens).

**Re-indexing strategy:** Track file `mtime` in the chunk payload. At startup, compare mtime to stored value — re-index only if the file changed.

---

## Gap 2 (HIGH): No Minimum Score Threshold for Memory Retrieval

### Problem
`agent.py:100-108` retrieves the top-5 episodic and top-3 semantic results with no minimum score filter. If semantic memory is sparse or the query is unrelated to stored facts, low-relevance noise gets injected into the prompt anyway.

Example: asking "what time is it?" would inject the top-3 semantic facts regardless of their relevance (score could be 0.15).

### Recommendation
Add a `min_score` parameter to `MemoryManager.search()` and apply a sensible default cutoff in `agent.py`.

**In `memory_manager.py`:**
```python
def search(self, ..., min_score: float = 0.0) -> List[Dict[str, Any]]:
    ...
    # After scoring, filter before returning
    processed_results = [r for r in processed_results if r["score"] >= min_score]
```

**In `agent.py`:**
```python
episodic_results = self.memory.search(
    query=message, memory_type="episodic", limit=5, min_score=0.30
)
semantic_results = self.memory.search(
    query=message, memory_type="semantic", limit=3, min_score=0.35
)
```

**Suggested thresholds (tune empirically):**
- Episodic: `0.30` — recent conversation context has lower semantic variance, lower bar is fine
- Semantic: `0.35` — facts should be meaningfully related to the query

---

## Gap 3 (HIGH): Flat Importance Score for All Episodic Memories

### Problem
Every episodic memory is stored with `importance=0.5` (the default). A user saying "hello" and a user saying "we are switching the primary model to Claude" are scored identically. High-signal turns get no retrieval advantage.

### Recommendation
Score episodic importance heuristically at write time in `agent.py` based on simple signals:

```python
def _score_importance(text: str) -> float:
    """Heuristic importance score for an episodic memory."""
    HIGH_SIGNALS = ["decision:", "remember:", "important:", "never ", "always ",
                    "decided", "switched", "replaced", "changed", "critical"]
    LOW_SIGNALS  = ["hello", "thanks", "ok", "sure", "got it", "sounds good"]
    text_lower = text.lower()
    if any(s in text_lower for s in HIGH_SIGNALS):
        return 0.9
    if any(s in text_lower for s in LOW_SIGNALS):
        return 0.2
    return 0.5
```

Then at write time:
```python
self.memory.add_memory(
    text=user_text,
    memory_type="episodic",
    importance=_score_importance(message),
    metadata={"session_id": session_id, "role": "user"},
)
```

This is intentionally simple. The `importance_weight=0.3` in the existing scorer means high-importance turns get a meaningful boost without dominating similarity.

---

## Gap 4 (MEDIUM): ConversationSummarizer Uses a Poor Retrieval Query

### Problem
`summarizer.py:75` retrieves episodic memories with `query="conversation summary"`. This searches for memories *semantically close to the phrase "conversation summary"* rather than the actual recent messages. Turns about shipping decisions, debugging sessions, or config changes may score poorly against this query and get excluded from the summary.

### Recommendation
Replace the vector query with a **metadata-filtered, timestamp-sorted** retrieval. Qdrant supports payload filtering — use it:

```python
# Instead of searching by "conversation summary",
# fetch by session_id metadata and sort chronologically
memories = self.memory.search(
    query=user_last_message,         # use actual content, not a static phrase
    memory_type="episodic",
    limit=self.turn_threshold * 2,
    filter_metadata={"session_id": session_id},
    min_score=0.0,                   # no score filter — we want all turns
)
# Then sort by timestamp ascending (already done in summarizer.py:89)
memories = [m for m in memories if not m.get("metadata", {}).get("is_summary")]
memories.sort(key=lambda m: m.get("timestamp", 0))
```

Longer term: add a `get_recent_episodic(session_id, limit)` method to `MemoryManager` that retrieves by timestamp directly rather than by vector similarity — episodic retrieval for summarization is fundamentally a chronological operation, not a semantic one.

---

## Gap 5 (MEDIUM): 30-Day Recency Decay Is Hardcoded and Too Short

### Problem
`memory_manager.py:152`:
```python
recency = max(0, 1 - (age_seconds / (30 * 24 * 3600)))
```

For an always-on agent with months of history, any memory older than 30 days gets `recency=0`. Important architectural decisions from 5 weeks ago compete on equal footing with last week's small talk. The decay cliff at day 30 is arbitrary.

### Recommendation
Two changes:

**1. Make the decay window configurable via settings:**
```python
# core/config.py
memory_recency_decay_days: int = Field(default=90)
```

**2. Use a gentler exponential decay instead of linear:**
```python
# memory_manager.py
import math
half_life_seconds = settings.memory_recency_decay_days * 24 * 3600 / 2
recency = math.exp(-0.693 * age_seconds / half_life_seconds)
# This gives 1.0 at age=0, 0.5 at age=half_life, never reaches 0
```

Exponential decay is more appropriate — importance fades gradually rather than falling off a cliff. With `decay_days=90`, a memory from 45 days ago still has a recency score of 0.5.

---

## Gap 6 (MEDIUM): SOUL.md Injected Wholesale Into Every Prompt

### Problem
`agent.py:113-114` reads the entire `SOUL.md` file on every turn. `SOUL.md` is currently ~120 lines. As it grows with new values, lessons, and capabilities, it will become an increasingly expensive fixed cost per call.

### Recommendation
Keep full SOUL.md injection for now — it is the agent's identity and should be fully present. **However**, add a size guard and a split strategy for when it grows:

**Short term:** Add a startup warning if `SOUL.md` exceeds 2,000 tokens (~8,000 characters):
```python
if len(soul_content) > 8000:
    logger.warning("SOUL.md is large (%d chars). Consider splitting into SOUL_CORE.md + SOUL_EXTENDED.md", len(soul_content))
```

**Medium term (when SOUL.md > 10k chars):** Split into:
- `SOUL_CORE.md` — always injected (identity, values, hard rules ~500 tokens)
- `SOUL_EXTENDED.md` — indexed into semantic memory, retrieved selectively

This is not urgent today but should be planned for before `SOUL.md` exceeds 300 lines.

---

## Gap 7 (MEDIUM): Background Extraction Races With Next Query

### Problem
`agent.py:295-309` fires `SemanticExtractor`, `LessonExtractor`, and `ConversationSummarizer` as `asyncio.create_task()` — non-blocking fire-and-forget. If the user sends a follow-up message within ~1-2 seconds (before extraction finishes), the facts from the previous turn haven't been stored yet, so they won't appear in semantic retrieval for the next query.

### Recommendation
Two approaches depending on tolerance:

**Option A — Tolerate the race (current behavior), add logging:**
Log when background tasks complete so the delay is visible in telemetry. Acceptable for most use cases since LLM response time (~2-3s) provides a natural buffer that usually covers extraction time.

**Option B — Add a lightweight "pending facts" in-process buffer:**
```python
# In Agent
self._pending_semantic_facts: List[str] = []

# SemanticExtractor appends to buffer synchronously
# At the start of process_message, flush pending facts into the semantic query
```
This adds complexity. Only implement if the race is observed in practice causing repeated misses.

**Recommendation: go with Option A.** Add telemetry timing to `SemanticExtractor` and `LessonExtractor` completions. If extraction consistently takes >3s (slower than the LLM response), revisit.

---

## Gap 8 (MEDIUM): Tool Results Are Never Stored in Memory

### Problem
When the agent executes a skill (e.g., `run_command`, `read_file`), the tool result is appended to the message list for the LLM to see — but it is never written to episodic memory. After the session ends, the fact that "I ran `df -h` and the disk was 85% full" is lost.

### Recommendation
After successful tool execution in the native tool call path (`agent.py:245-246`), store a condensed version in episodic memory:

```python
# After executing tool, store result summary
tool_summary = f"Tool {fn_name} called with {args}. Result: {str(result)[:300]}"
self.memory.add_memory(
    text=tool_summary,
    memory_type="episodic",
    importance=0.7,   # tool results are higher signal than conversation filler
    metadata={"session_id": session_id, "role": "tool", "tool_name": fn_name},
)
```

Keep it at 300 chars max — the full result can be very large (e.g., `read_file` output). The summary preserves the fact that the action was taken and its rough outcome.

---

## Gap 9 (MEDIUM): Two Separate LLM Calls Per Turn for Extraction

### Problem
After each turn, both `SemanticExtractor` and `LessonExtractor` independently call the LLM on the same conversation turn — two inference calls for what is effectively one analysis task.

### Recommendation
Merge into a single `TurnAnalyzer` that runs one LLM call and returns both facts and lessons:

```python
_COMBINED_PROMPT = """\
Analyze this conversation turn. Return a JSON object with two keys:

"facts": array of durable factual strings to remember long-term (user preferences,
         decisions, technical choices). Return [] if none.

"lessons": array of objects [{title, context, lesson}] capturing corrections,
           preference signals, or better approaches discovered. Return [] if none.

User: {user_message}
Assistant: {assistant_response}"""
```

This halves the post-turn LLM overhead and reduces the chance of the two extractors producing redundant/conflicting entries about the same turn.

**Migration path:** Keep `SemanticExtractor` and `LessonExtractor` as separate classes (don't delete them — they have their own storage logic). Add a `CombinedTurnExtractor` that calls the LLM once and delegates results to both.

---

## Gap 10 (LOW): No Episodic Memory Eviction

### Problem
The episodic collection grows indefinitely. Every message from every session is stored forever. After months of use, episodic will contain thousands of "Hello", "Thanks", "OK" turns that add noise to retrieval.

### Recommendation
Add a background maintenance task to the `HeartbeatSystem` (weekly cron) that:
1. Retrieves all episodic entries older than N days with `importance < 0.3`
2. Deletes them from Qdrant

```python
# heartbeat/integrations/memory_maintenance.py
class MemoryMaintenanceTask(HeartbeatIntegration):
    name = "memory_maintenance"

    async def check(self) -> dict:
        cutoff = time.time() - (self.retention_days * 86400)
        # Use qdrant scroll + filter: timestamp < cutoff AND importance < 0.3
        deleted = self.vector_store.delete_old_low_importance(
            collection="episodic",
            before_timestamp=cutoff,
            max_importance=0.3,
        )
        return {"deleted": deleted}
```

This requires adding a `delete_by_filter()` method to `VectorStore` (Qdrant supports this natively).

**Safe defaults:** `retention_days=60`, `max_importance=0.3` — only deletes old, low-signal turns.

---

## Implementation Priority

| Gap | File(s) | Effort | Impact |
|-----|---------|--------|--------|
| 1. USER.md/MEMORY.md not indexed | `memory/static_loader.py` (new), `main.py` | Medium | High |
| 2. No min_score threshold | `memory_manager.py`, `core/agent.py` | Small | High |
| 3. Flat importance=0.5 | `core/agent.py` | Small | Medium |
| 4. Summarizer bad query | `memory/summarizer.py` | Small | Medium |
| 5. 30-day decay cliff | `memory_manager.py`, `core/config.py` | Small | Medium |
| 6. SOUL.md size guard | `core/agent.py` | Tiny | Low (future) |
| 7. Background race | `core/agent.py` | Small | Low |
| 8. Tool results not stored | `core/agent.py` | Small | Medium |
| 9. Two LLM calls per turn | `memory/` (new `combined_extractor.py`) | Medium | Medium |
| 10. No episodic eviction | `memory/` (new), `core/heartbeat.py` | Medium | Low |

---

## Recommended Implementation Order

### Phase 1 — Quick wins (1-2 hours)
1. Gap 2: Add `min_score` to `MemoryManager.search()` and apply in `agent.py`
2. Gap 3: Add `_score_importance()` heuristic in `agent.py`
3. Gap 4: Fix `ConversationSummarizer` query strategy
4. Gap 5: Exponential decay + configurable window in `memory_manager.py`

### Phase 2 — Indexing static files (2-4 hours)
5. Gap 1: Build `StaticFileLoader`, index USER.md + MEMORY.md into semantic collection

### Phase 3 — Richer episodic memory (1-2 hours)
6. Gap 8: Store tool results in episodic memory

### Phase 4 — Optimization (3-5 hours)
7. Gap 9: Merge extractors into `CombinedTurnExtractor`
8. Gap 10: Add `MemoryMaintenanceTask` to heartbeat system

### Phase 5 — Future (when SOUL.md grows large)
9. Gap 6: SOUL.md split strategy
10. Gap 7: Revisit background race if telemetry shows consistent misses

---

## Success Metrics

After Phase 1-2, verify:
- `GET /api/memory/search?q=timezone` returns a result from USER.md content
- `GET /api/memory/search?q=python decision` returns the architecture decision from MEMORY.md
- Memory search for an unrelated query returns 0 or fewer results (min_score filtering working)
- High-signal turns ("we decided to switch to Claude") have `importance >= 0.9` in Qdrant payload
- ConversationSummarizer produces coherent summaries that include recent tool calls and decisions (not just conversational turns)

---

## Implementation Status

**Date completed:** 2026-03-28
**All 10 gaps implemented and tests passing.**

| Gap | Status | Files Changed |
|-----|--------|---------------|
| Gap 1: USER.md/MEMORY.md indexing | DONE | `memory/static_loader.py` (new), `main.py` |
| Gap 2: No min_score threshold | DONE | `memory/memory_manager.py`, `core/agent.py` |
| Gap 3: Flat importance=0.5 | DONE | `core/agent.py` (`_score_importance()` added) |
| Gap 4: Summarizer bad query | DONE | `memory/summarizer.py` (query changed to broad conversational anchor) |
| Gap 5: 30-day decay cliff | DONE | `memory/memory_manager.py` (exponential decay + `recency_decay_days`), `core/config.py` |
| Gap 6: SOUL.md size guard | DONE | `core/agent.py` (8000-char warning added) |
| Gap 7: Background race logging | DONE | `core/agent.py` (timing telemetry on all background tasks) |
| Gap 8: Tool results not stored | DONE | `core/agent.py` (episodic write after each tool call in both native + ReAct paths) |
| Gap 9: Two LLM calls per turn | DONE | `memory/combined_extractor.py` (new), `core/agent.py`, `main.py` |
| Gap 10: No episodic eviction | DONE | `heartbeat/integrations/memory_maintenance.py` (new), `memory/vector_store.py` (`delete_by_filter()`), `main.py` |

### New test files added
- `tests/memory/test_static_loader.py` — 11 tests for `StaticFileLoader`
- `tests/memory/test_combined_extractor.py` — 8 tests for `CombinedTurnExtractor`
- `tests/heartbeat/test_memory_maintenance.py` — 4 tests for `MemoryMaintenanceTask`
- `tests/memory/test_memory_manager.py` — extended with `min_score`, exponential decay, and `recency_decay_days` tests
- `tests/memory/test_vector_store.py` — extended with `delete_by_filter` test
- `tests/core/test_agent.py` — extended with `_score_importance`, `min_score`, importance-on-episodic-write tests

### Validation notes
- `memory/__init__.py` updated to export `CombinedTurnExtractor` and `StaticFileLoader`
- `tests/memory/__init__.py` created to ensure pytest discovery in that package
