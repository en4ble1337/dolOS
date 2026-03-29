# Memory Improvements — Change Log

**Date:** 2026-03-28
**Branch:** main
**Related plan:** `docs/plans/2026-03-28-memory-improvements.md`

This document records every file added or modified as part of the 10-gap memory improvement implementation. Use `git diff <commit>` against the commit before these changes to see exact diffs.

---

## New Files

### `memory/static_loader.py`
**Purpose (Gap 1):** Indexes static Markdown files (`USER.md`, `MEMORY.md`) into the Qdrant semantic collection at startup so the agent can retrieve relevant sections via vector search rather than never seeing them.

Key behaviour:
- Chunks files by paragraph, then by character (400-char chunks, 80-char overlap)
- Tracks file `mtime` — skips re-indexing if file is unchanged
- Stores chunks with `importance=0.6`, metadata: `{source, chunk_index, mtime, path}`

### `memory/combined_extractor.py`
**Purpose (Gap 9):** Replaces two separate post-turn LLM calls (SemanticExtractor + LessonExtractor) with one combined call that returns both facts and lessons in a single JSON response.

Key behaviour:
- One `llm.generate()` call per turn
- Parses `{"facts": [...], "lessons": [...]}` JSON with markdown-fence stripping and regex fallback
- Delegates storage to existing `SemanticExtractor` and `LessonExtractor` internals (dedup logic preserved)
- Falls back to separate extractors if `combined_extractor` is not configured

### `heartbeat/integrations/memory_maintenance.py`
**Purpose (Gap 10):** Weekly heartbeat task that evicts old, low-importance episodic memories to prevent unbounded Qdrant collection growth.

Key behaviour:
- Runs every Sunday at 02:00 via APScheduler cron
- Deletes episodic entries older than `retention_days=60` days with `importance < 0.3`
- Returns `{deleted, retention_days, cutoff}` for telemetry

### `tests/memory/test_static_loader.py`
11 tests covering: chunk-and-store, missing file, mtime skip, mtime-changed re-index, chunk sizing, overlap correctness, empty input.

### `tests/memory/test_combined_extractor.py`
8 tests covering: valid facts+lessons, empty facts, malformed JSON (no crash), single LLM call assertion.

### `tests/heartbeat/test_memory_maintenance.py`
4 tests covering: delete_by_filter called with correct args, deleted count returned, cutoff calculation.

### `tests/memory/__init__.py`
Empty file — required for pytest package resolution of new test files.

---

## Modified Files

### `memory/memory_manager.py`
**Changes (Gaps 2 + 5):**
- Added `import math`
- Added `recency_decay_days: int = 90` constructor parameter
- Replaced 30-day linear recency decay with exponential: `math.exp(-0.693 * age_seconds / half_life_seconds)` — never reaches zero, gradual fade
- Added `min_score: float = 0.0` parameter to `search()` — filters results below threshold before returning

**Before (recency):**
```python
recency = max(0, 1 - (age_seconds / (30 * 24 * 3600)))
```
**After:**
```python
half_life_seconds = self.recency_decay_days * 24 * 3600
recency = math.exp(-0.693 * age_seconds / half_life_seconds)
```

### `memory/summarizer.py`
**Change (Gap 4):** Fixed broken vector search query in `summarize_session()`.

**Before:** `query="conversation summary"` — biased retrieval toward text semantically close to the phrase "conversation summary", missing debugging logs, config changes, and casual turns.

**After:** `query="user assistant conversation exchange message"` — broad anchor that matches general conversational turns. The `filter_metadata={"session_id": session_id}` remains the primary scope constraint.

### `memory/vector_store.py`
**Change (Gap 10):** Added `delete_by_filter(collection_name, before_timestamp, max_importance) -> int` method using Qdrant's `Filter` with `Range` conditions. Used by `MemoryMaintenanceTask`.

### `memory/__init__.py`
Added `StaticFileLoader` and `CombinedTurnExtractor` to exports and `__all__`.

### `core/config.py`
**Change (Gap 5):** Added `memory_recency_decay_days: int = Field(default=90)` to `Settings`. Controls the half-life of the recency decay function.

### `core/agent.py`
**Changes (Gaps 2, 3, 6, 7, 8, 9):**

| Change | Location | Purpose |
|--------|----------|---------|
| `_score_importance()` function added | Module level | Heuristic: 0.9 for decision/switch/critical signals, 0.2 for hello/thanks, 0.5 neutral |
| `importance=_score_importance(...)` on all episodic writes | `process_message()` | High-signal turns surface better in retrieval |
| `min_score=0.30` on episodic search | `process_message()` | Prevents low-relevance noise in prompt |
| `min_score=0.35` on semantic search | `process_message()` | Same — stricter for long-term facts |
| SOUL.md size guard | After soul_content read | Logs warning if SOUL.md > 8,000 chars |
| Tool result episodic write | After each tool execution (both paths) | Preserves what tools did in memory across sessions |
| Timing telemetry on background tasks | `_run_*` methods | Warns if extraction takes >3s (race risk) |
| `combined_extractor` optional param | `__init__`, `_schedule_background_tasks` | Routes to single-LLM-call path when both extractors are enabled |
| `_run_combined_extraction()` method added | New async runner | Executes `CombinedTurnExtractor.extract_and_store()` with timing |

### `main.py`
**Changes (Gaps 1, 9, 10):**

| Change | Purpose |
|--------|---------|
| `from memory.static_loader import StaticFileLoader` | Gap 1 |
| `from memory.combined_extractor import CombinedTurnExtractor` | Gap 9 |
| `from heartbeat.integrations.memory_maintenance import MemoryMaintenanceTask` | Gap 10 |
| `MemoryManager(..., recency_decay_days=settings.memory_recency_decay_days)` | Gap 5 — passes config to MemoryManager |
| `StaticFileLoader(memory).index_file(...)` called for USER.md + MEMORY.md | Gap 1 — runs at startup |
| `CombinedTurnExtractor(llm, semantic_extractor, lesson_extractor)` instantiated | Gap 9 — only when both extractors are enabled |
| `combined_extractor=combined_extractor` passed to `Agent(...)` | Gap 9 |
| `MemoryMaintenanceTask` registered as weekly cron (Sun 02:00) | Gap 10 |

### `tests/memory/test_memory_manager.py`
Extended with 4 new tests: `min_score` filtering, `min_score=0.0` baseline, exponential-never-zero, half-life accuracy.

### `tests/memory/test_summarizer.py`
Added regression test asserting the query is no longer `"conversation summary"`.

### `tests/memory/test_vector_store.py`
Added `test_delete_by_filter_removes_old_low_importance` with 3-point fixture.

### `tests/core/test_agent.py`
Added `TestScoreImportance` class (5 tests). Updated existing tests to include `importance=` kwarg in `add_memory` mock assertions.

---

## Runtime Behaviour Change Summary

| What changed | Before | After |
|---|---|---|
| USER.md / MEMORY.md | Never seen by agent | Indexed into semantic memory at startup, retrieved per-query |
| Low-relevance memory in prompt | Always injected (no floor) | Filtered at score 0.30/0.35 |
| Episodic importance | Always 0.5 | 0.2–0.9 based on content signals |
| Recency decay | Linear, zeroes at 30 days | Exponential, 90-day half-life, never zero |
| Summarizer input | Biased toward "summary"-like text | All session turns retrieved equally |
| Post-turn LLM calls | 2 (SemanticExtractor + LessonExtractor) | 1 (CombinedTurnExtractor) |
| Tool results | Lost after session | Stored in episodic (300-char summary, importance=0.7) |
| Episodic collection size | Unbounded | Weekly eviction of entries >60 days, importance <0.3 |

---

## Rollback

All changes are in git. To revert:
```bash
git log --oneline   # find the commit hash before these changes
git revert <hash>   # or git reset --hard <hash> for full rollback
```

The new files (`static_loader.py`, `combined_extractor.py`, `memory_maintenance.py`) can also be individually removed without breaking existing functionality — `main.py` guards `CombinedTurnExtractor` instantiation behind a None check, and `StaticFileLoader` is called at startup with a graceful skip on missing files.
