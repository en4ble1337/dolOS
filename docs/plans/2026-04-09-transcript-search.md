# Transcript Search Implementation Plan

**Directive:** User brief to implement Phase F TranscriptIndex / FTS5 Transcript Search
**Date:** 2026-04-09
**Goal:** Add a SQLite FTS5 transcript index, wire incremental indexing into transcript writes, expose transcript search as a skill, and bulk-index existing transcript JSONL files on startup without duplicating rows.
**Architecture Notes:** Keep the index layer synchronous and stdlib-only in `memory/transcript_index.py`. Reuse the existing transcript append path in `storage/transcripts.py` so `core/agent.py` behavior stays unchanged, and wire the startup backfill through `loop.run_in_executor(...)` instead of creating an async task for synchronous indexing work.

---

### Task 1: Lock the Test Surface First

**Files:**
- Create/Modify: `docs/plans/2026-04-09-transcript-search.md`
- Create: `tests/memory/test_transcript_index.py`
- Modify: `tests/storage/test_transcripts.py`
- Create: `tests/skills/test_transcript_search_skill.py`

**Step 1:** Create the implementation plan file
- File: `docs/plans/2026-04-09-transcript-search.md`
- Run: `python -m pytest tests/memory/test_transcript_index.py -q`
- Expected: file missing or no tests collected yet

**Step 2:** Add failing transcript index tests
- File: `tests/memory/test_transcript_index.py`
- Add tests for:
  - `test_append_entry_indexes_single_transcript_entry`
  - `test_search_returns_hits_across_sessions`
  - `test_index_all_bulk_indexes_existing_jsonl_files`
  - `test_index_session_does_not_duplicate_already_indexed_rows`
  - `test_malformed_json_line_is_skipped`
  - `test_tool_call_entries_are_searchable`
  - `test_search_limit_is_respected`
- Run: `python -m pytest tests/memory/test_transcript_index.py -q`
- Expected: failures because `memory/transcript_index.py` does not exist yet

**Step 3:** Add failing transcript store integration tests
- File: `tests/storage/test_transcripts.py`
- Add tests for:
  - transcript append calls `append_entry()` when an index is configured
  - transcript append still succeeds if indexing raises
- Run: `python -m pytest tests/storage/test_transcripts.py -q`
- Expected: new failures because `TranscriptStore` does not accept or use a transcript index yet

**Step 4:** Add failing skill tests
- File: `tests/skills/test_transcript_search_skill.py`
- Add tests for:
  - no index configured returns a clear error
  - no hits returns a clear no-results message
  - hits return formatted output with session id, type, timestamp, and content
- Run: `python -m pytest tests/skills/test_transcript_search_skill.py -q`
- Expected: failures because `set_transcript_index()` and `search_transcripts()` do not exist yet

---

### Task 2: Implement the Transcript Index

**Files:**
- Create/Modify: `memory/transcript_index.py`

**Step 1:** Create the SQLite schema and initialization path
- File: `memory/transcript_index.py`
- Implement:
  - `TranscriptIndex.__init__(db_path: str = "data/transcript_index.db")`
  - `initialize()`
  - metadata table for per-session progress
  - FTS5 virtual table with `session_id`, `entry_type`, `content`, `timestamp UNINDEXED`
- Run: `python -m pytest tests/memory/test_transcript_index.py -q`
- Expected: failures move from import errors to behavioral mismatches

**Step 2:** Implement entry normalization and incremental writes
- File: `memory/transcript_index.py`
- Implement:
  - content extraction for `user`, `assistant`, `tool_result`
  - compact searchable text for `tool_call` using tool name plus arguments JSON
  - `append_entry()`
  - helper logic that skips entries with empty searchable text
- Run: `python -m pytest tests/memory/test_transcript_index.py -q`
- Expected: single-entry and tool-call tests begin passing

**Step 3:** Implement session and bulk backfill
- File: `memory/transcript_index.py`
- Implement:
  - `index_session()` using saved per-session line progress
  - malformed JSON line skip with safe continuation
  - `index_all()` across `data/transcripts/*.jsonl`
  - no duplicate rows when a session is re-indexed after prior appends
- Run: `python -m pytest tests/memory/test_transcript_index.py -q`
- Expected: all transcript index tests pass

**Step 4:** Implement search results
- File: `memory/transcript_index.py`
- Implement:
  - `search(query, limit=10)` returning dicts with `session_id`, `entry_type`, `content`, `timestamp`, and rank/score
  - stable limit handling
- Run: `python -m pytest tests/memory/test_transcript_index.py -q`
- Expected: search and limit tests pass

---

### Task 3: Integrate Transcript Writes and Transcript Search Skill

**Files:**
- Modify: `storage/transcripts.py`
- Modify: `skills/local/memory.py`

**Step 1:** Add transcript index injection to `TranscriptStore`
- File: `storage/transcripts.py`
- Implement:
  - optional transcript index in `__init__` or a setter
  - successful JSONL append followed by `transcript_index.append_entry(session_id, entry)`
  - warning log and continued transcript success if indexing fails
- Run: `python -m pytest tests/storage/test_transcripts.py -q`
- Expected: transcript store tests pass, including new integration coverage

**Step 2:** Add transcript index injection to the memory skill module
- File: `skills/local/memory.py`
- Implement:
  - module-level `_transcript_index`
  - `set_transcript_index(index) -> None`
  - `search_transcripts(query: str, limit: int = 10) -> str`
- Run: `python -m pytest tests/skills/test_transcript_search_skill.py -q`
- Expected: skill tests pass

**Step 3:** Format transcript search output for operator usefulness
- File: `skills/local/memory.py`
- Ensure output includes:
  - session id
  - type
  - timestamp
  - readable content preview
- Run: `python -m pytest tests/skills/test_transcript_search_skill.py -q`
- Expected: formatting assertions pass

---

### Task 4: Wire Startup Initialization

**Files:**
- Modify: `main.py`

**Step 1:** Construct and initialize the transcript index
- File: `main.py`
- Implement:
  - `TranscriptIndex(db_path="data/transcript_index.db")`
  - `initialize()`
  - injection into `TranscriptStore`
  - injection via `skills.local.memory.set_transcript_index(...)`
- Run: `python -m pytest tests/memory/test_transcript_index.py tests/storage/test_transcripts.py tests/skills/test_transcript_search_skill.py -q`
- Expected: targeted tests still pass after wiring changes

**Step 2:** Schedule startup bulk indexing correctly
- File: `main.py`
- Implement:
  - `loop.run_in_executor(None, transcript_index.index_all, Path("data/transcripts"))`
  - place startup backfill inside lifespan startup flow, not `asyncio.create_task(...)`
- Run: `python -m pytest tests/memory/test_transcript_index.py tests/storage/test_transcripts.py tests/skills/test_transcript_search_skill.py -q`
- Expected: targeted tests still pass

---

### Task 5: Verification and Review

**Files:**
- Modify only if verification reveals defects

**Step 1:** Run transcript index tests
- Run: `python -m pytest tests/memory/test_transcript_index.py -q`
- Expected: all pass

**Step 2:** Run transcript and skill integration tests
- Run: `python -m pytest tests/storage/test_transcripts.py tests/skills/test_transcript_search_skill.py -q`
- Expected: all pass

**Step 3:** Run suite stop-on-first-failure checkpoint
- Run: `python -m pytest tests/ -x -q`
- Expected: stop in the existing failure set only

**Step 4:** Run full suite count
- Run: `python -m pytest tests/ -q`
- Expected: no new failures beyond the current baseline; remaining failures stay confined to `tests/core/test_agent.py` and `tests/core/test_llm.py`

**Step 5:** Spec compliance review
- Confirm:
  - transcript index uses SQLite FTS5 only
  - tool-call entries are searchable
  - malformed JSON is skipped safely
  - session re-indexing is incremental and non-duplicating
  - transcript writes never fail because indexing fails
  - startup bulk indexing uses `run_in_executor(...)`

**Step 6:** Code quality review
- Confirm:
  - index logic stays importable without external services
  - startup wiring is narrow and synchronous work stays off the event loop
  - search output is concise but useful for agent/tool consumption
