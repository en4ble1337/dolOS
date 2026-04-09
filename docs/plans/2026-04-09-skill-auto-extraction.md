# Skill Auto-Extraction Implementation Plan

**Directive:** User brief for Phase B SkillExtractionTask (`directives/` missing in this checkout)
**Date:** 2026-04-09
**Goal:** Add a post-turn background task that evaluates multi-tool turns for reusable patterns, deduplicates against existing skills, and creates quarantined generated skills automatically.
**Architecture Notes:** Follow the single-call background extraction pattern already used by `memory/combined_extractor.py`: one guarded LLM call, parse structured JSON, emit telemetry, never crash the agent loop. Wire the new task through `main.py` and `core/agent.py` so it stays optional and only runs for turns with enough tool usage to justify extraction.

---

### Task 1: Plan and Test Surface

**Files:**
- Create/Modify: `docs/plans/2026-04-09-skill-auto-extraction.md`
- Modify: `tests/memory/test_skill_extractor.py`
- Modify: `tests/core/test_agent.py`

**Step 1:** Create the implementation plan file
- File: `docs/plans/2026-04-09-skill-auto-extraction.md`
- Run: `python -m pytest tests/memory/test_skill_extractor.py -q`
- Expected: test collection fails because `tests/memory/test_skill_extractor.py` does not exist yet

**Step 2:** Write failing extractor tests
- File: `tests/memory/test_skill_extractor.py`
- Add tests for:
  - minimum tool threshold short-circuit
  - `should_create=false`
  - valid skill creation
  - embedding duplicate skip
  - LLM exception handling
  - invalid JSON handling
  - flag passthrough for `is_read_only` and `concurrency_safe`
- Run: `python -m pytest tests/memory/test_skill_extractor.py -q`
- Expected: failures caused by missing `memory.skill_extractor.SkillExtractionTask`

**Step 3:** Write failing agent wiring tests
- File: `tests/core/test_agent.py`
- Add tests for:
  - native tool calls passed to `_schedule_background_tasks(..., tool_calls_made=...)`
  - ReAct tool calls also included in `tool_calls_made`
  - background scheduling only fires skill extraction when threshold is met
- Run: `python -m pytest tests/core/test_agent.py -q`
- Expected: failures caused by missing `skill_extractor` support and missing `tool_calls_made` argument

---

### Task 2: Implement SkillExtractionTask

**Files:**
- Create/Modify: `memory/skill_extractor.py`

**Step 1:** Add `SkillExtractionTask` skeleton and parse helpers
- File: `memory/skill_extractor.py`
- Implement:
  - `MIN_TOOL_CALLS = 3`
  - constructor storing `llm`, `registry`, `event_bus`
  - prompt template with required JSON fields including `is_read_only` and `concurrency_safe`
  - `evaluate_and_extract(...)` early returns for `llm is None` and below-threshold tool usage
- Run: `python -m pytest tests/memory/test_skill_extractor.py -q`
- Expected: failures move from import errors to behaviour assertions

**Step 2:** Add JSON parsing, LLM failure handling, and telemetry emission
- File: `memory/skill_extractor.py`
- Implement:
  - one `llm.generate(...)` call with `messages=[{"role": "user", "content": prompt}]`
  - `SKILL_EXTRACTION_START`, `SKILL_EXTRACTION_SKIP`, and `SKILL_EXTRACTION_ERROR` emissions
  - fenced-JSON tolerant parsing
  - warning log and `return 0` on LLM failure or parse failure
- Run: `python -m pytest tests/memory/test_skill_extractor.py -q`
- Expected: skip/error-path tests pass

**Step 3:** Add duplicate detection and skill creation
- File: `memory/skill_extractor.py`
- Implement:
  - exact name-match duplicate check always
  - embedding-based duplicate check using `registry._embedder.encode(description)` and cosine similarity against `registration.description_embedding`
  - fallback to name-only when embeddings unavailable
  - `await create_skill(name, description, code, is_read_only, concurrency_safe)` on success
  - `SKILL_EXTRACTION_DUPLICATE` and `SKILL_EXTRACTION_CREATED` emissions
- Run: `python -m pytest tests/memory/test_skill_extractor.py -q`
- Expected: all extractor tests pass

---

### Task 3: Wire Agent and Main

**Files:**
- Modify: `core/telemetry.py`
- Modify: `core/agent.py`
- Modify: `main.py`

**Step 1:** Extend telemetry enum for Phase B
- File: `core/telemetry.py`
- Add:
  - `SKILL_EXTRACTION_START`
  - `SKILL_EXTRACTION_SKIP`
  - `SKILL_EXTRACTION_DUPLICATE`
  - `SKILL_EXTRACTION_CREATED`
  - `SKILL_EXTRACTION_ERROR`
- Run: `python -m pytest tests/memory/test_skill_extractor.py tests/core/test_agent.py -q`
- Expected: event enum references resolve

**Step 2:** Thread `skill_extractor` through `Agent`
- File: `core/agent.py`
- Implement:
  - `TYPE_CHECKING` import for `SkillExtractionTask`
  - optional `skill_extractor` constructor parameter and `self.skill_extractor`
  - `tool_calls_made: list[str] = []` in `process_message`
  - append tool names in native and ReAct execution paths
  - pass `tool_calls_made` into `_schedule_background_tasks(...)`
  - inside `_schedule_background_tasks`, create the background skill extraction task only when threshold is met
- Run: `python -m pytest tests/core/test_agent.py -q`
- Expected: new agent tests pass and existing agent tests remain green except known pre-existing failures

**Step 3:** Wire construction in `main.py`
- File: `main.py`
- Implement:
  - `registry.set_embedder(memory.embedding_service)` after memory setup
  - `SkillExtractionTask(llm=llm, registry=registry, event_bus=event_bus)`
  - pass `skill_extractor=skill_extractor` into `Agent(...)`
- Run: `python -m pytest tests/memory/test_skill_extractor.py tests/core/test_agent.py -q`
- Expected: import and construction paths stay valid

---

### Task 4: Verification and Review

**Files:**
- Modify as needed from prior tasks only if tests expose defects

**Step 1:** Run targeted verification
- Run: `python -m pytest tests/memory/test_skill_extractor.py tests/core/test_agent.py -q`
- Expected: targeted tests pass

**Step 2:** Run full requested suite
- Run: `python -m pytest tests/ -x -q`
- Expected: 604 passed, 11 failed (only the known pre-existing failures in `test_agent.py` and `test_llm.py`)

**Step 3:** Spec compliance review
- Confirm:
  - no changes to `core/agent.py:151-155`
  - auto-extracted skills default to `False/False` when uncertain
  - LLM failure path logs and returns `0` without side effects
  - dedupe uses description embeddings when available, exact name otherwise

**Step 4:** Code quality review
- Confirm:
  - extractor is isolated and optional
  - background task scheduling remains non-blocking
  - tests cover threshold, duplicate, parse, and flag passthrough cases
