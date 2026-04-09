# Skill Auto-Fix Implementation Plan

**Directive:** User brief to proceed to Phase C of the self-improving agent roadmap
**Date:** 2026-04-09
**Goal:** Automatically repair generated skills after runtime failure, rewrite them through the existing quarantine gate, and only re-execute the repaired skill when it is read-only.
**Architecture Notes:** Keep the entire Phase C workflow inside `skills/executor.py` so failures remain localized to skill execution. Reuse `fix_skill()` and `create_skill()` from `skills/local/meta.py` instead of inventing a new persistence path, and emit explicit telemetry for attempt/success/failure so the auto-fix path is visible.

---

### Task 1: Define the Test Surface

**Files:**
- Create/Modify: `docs/plans/2026-04-09-skill-auto-fix.md`
- Modify: `tests/skills/test_skill_auto_fix.py`
- Modify: `tests/core/test_telemetry.py`

**Step 1:** Create the implementation plan file
- File: `docs/plans/2026-04-09-skill-auto-fix.md`
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py -q`
- Expected: existing Phase A2 tests run; no Phase C coverage yet

**Step 2:** Add failing Phase C executor tests
- File: `tests/skills/test_skill_auto_fix.py`
- Add tests for:
  - built-in skill failure never enters auto-fix
  - generated skill timeout triggers auto-fix attempt
  - read-only generated skill failure rewrites and re-executes
  - mutating generated skill failure rewrites but does not re-execute
  - failed auto-fix returns the original error cleanly
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py -q`
- Expected: new tests fail because `SkillExecutor` has no auto-fix path yet

**Step 3:** Add failing telemetry enum checks
- File: `tests/core/test_telemetry.py`
- Add assertions for:
  - `SKILL_AUTO_FIX_ATTEMPT`
  - `SKILL_AUTO_FIX_SUCCESS`
  - `SKILL_AUTO_FIX_FAILED`
- Update total enum count expectation
- Run: `python -m pytest tests/core/test_telemetry.py -k \"auto_fix or total_event_count\" -q`
- Expected: failures because the new event types do not exist yet

---

### Task 2: Implement Auto-Fix in SkillExecutor

**Files:**
- Modify: `skills/executor.py`

**Step 1:** Extend constructor and execution flow
- File: `skills/executor.py`
- Implement:
  - optional `llm` dependency in `SkillExecutor.__init__`
  - `_fix_attempted` tracking scoped by current trace
  - internal helper flow so recursive re-execution can disable another auto-fix attempt
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py -q`
- Expected: failures move from missing control flow to specific behavior mismatches

**Step 2:** Add `_attempt_auto_fix()` and parsing helpers
- File: `skills/executor.py`
- Implement:
  - generated-skill detection via `skills/local/generated/{name}.py`
  - `fix_skill(name)` source retrieval
  - single LLM call asking for corrected `async def handler(...)` code only
  - fenced-code tolerant handler extraction
  - `create_skill(...)` rewrite using existing description and safety flags
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py -q`
- Expected: auto-fix attempt tests begin passing

**Step 3:** Enforce read-only retry safety and telemetry
- File: `skills/executor.py`
- Implement:
  - only re-execute automatically when the generated skill registration is `is_read_only=True`
  - return a re-invoke message for mutating skills after successful rewrite
  - emit `SKILL_AUTO_FIX_ATTEMPT`, `SKILL_AUTO_FIX_SUCCESS`, `SKILL_AUTO_FIX_FAILED`
  - fall back to the original execution error if the fix flow fails
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py tests/skills/test_executor.py -q`
- Expected: Phase C tests and existing executor tests pass

---

### Task 3: Wire Telemetry and Main

**Files:**
- Modify: `core/telemetry.py`
- Modify: `main.py`

**Step 1:** Add Phase C telemetry enum entries
- File: `core/telemetry.py`
- Add:
  - `SKILL_AUTO_FIX_ATTEMPT = "skill.auto_fix.attempt"`
  - `SKILL_AUTO_FIX_SUCCESS = "skill.auto_fix.success"`
  - `SKILL_AUTO_FIX_FAILED = "skill.auto_fix.failed"`
- Run: `python -m pytest tests/core/test_telemetry.py -k \"auto_fix or total_event_count\" -q`
- Expected: telemetry tests pass

**Step 2:** Pass `llm` into `SkillExecutor` construction
- File: `main.py`
- Update the executor wiring to `SkillExecutor(registry=registry, event_bus=event_bus, llm=llm)`
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py tests/skills/test_executor.py tests/core/test_telemetry.py -q`
- Expected: targeted tests pass

---

### Task 4: Verification and Review

**Files:**
- Modify as needed only if verification exposes defects

**Step 1:** Run targeted verification
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py tests/skills/test_executor.py tests/core/test_telemetry.py -q`
- Expected: all targeted tests pass

**Step 2:** Run required suite checkpoint
- Run: `python -m pytest tests/ -x -q`
- Expected: stop at the first pre-existing failure in `tests/core/test_agent.py`

**Step 3:** Run full suite count
- Run: `python -m pytest tests/ -q`
- Expected: existing `tests/core/test_agent.py` and `tests/core/test_llm.py` failures remain, with no new Phase C regressions

**Step 4:** Spec compliance review
- Confirm:
  - built-in skills never enter auto-fix path
  - generated mutating skills are not auto-retried
  - generated read-only skills are auto-retried once
  - max one auto-fix attempt occurs per trace/name

**Step 5:** Code quality review
- Confirm:
  - auto-fix logic is isolated to `SkillExecutor`
  - all failures degrade cleanly to the original error path
  - helper parsing is minimal and does not rewrite non-handler module text into `create_skill()`
