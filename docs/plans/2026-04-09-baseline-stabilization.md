# Baseline Stabilization Implementation Plan

**Directive:** None present in `directives/` on 2026-04-09
**Date:** 2026-04-09
**Goal:** Remove the remaining baseline failures in `tests/core/test_agent.py` and `tests/core/test_llm.py` without changing unrelated behavior.
**Architecture Notes:** `core/agent.py` already treats several `llm.settings` reads as optional, so the failing access to `primary_model` should be hardened the same way. `core/llm.py` intentionally remaps `ollama/...` models to the OpenAI-compatible `/v1` endpoint for LiteLLM tool-call parsing, so the LLM tests need to assert that behavior explicitly instead of the old direct-Ollama call shape.

---

### Task 1: Document the intended LLM remap behavior in tests

**Files:**
- Create/Modify: `tests/core/test_llm.py`

**Step 1:** Update the settings fixture to make Ollama remapping deterministic
- File: `tests/core/test_llm.py`
- Code: set `ollama_api_base="http://localhost:11434"` in the shared `Settings(...)` fixture so the remap path is exercised consistently.

**Step 2:** Update the success-path assertions
- File: `tests/core/test_llm.py`
- Code: assert the LiteLLM call uses `model="openai/llama3"`, `api_base="http://localhost:11434/v1"`, and `api_key="ollama"`, while telemetry still reports `ollama/llama3`.

**Step 3:** Update the fallback-path assertions
- File: `tests/core/test_llm.py`
- Code: assert the first LiteLLM call uses the remapped OpenAI-compatible Ollama model and the second call uses `gpt-4-turbo`.

**Step 4:** Run the focused LLM tests
- Run: `python -m pytest tests/core/test_llm.py -q`
- Expected: all tests in `tests/core/test_llm.py` pass.

---

### Task 2: Harden `Agent` against missing `llm.settings`

**Files:**
- Create/Modify: `core/agent.py`
- Create/Modify: `tests/core/test_agent.py`

**Step 1:** Keep the existing failing agent tests as the RED signal
- Run: `python -m pytest tests/core/test_agent.py -q`
- Expected: failures show `AttributeError: Mock object has no attribute 'settings'`.

**Step 2:** Add a focused regression test for optional settings access if needed
- File: `tests/core/test_agent.py`
- Code: only add a new test if the existing failing tests do not fully capture the missing-settings behavior.

**Step 3:** Replace the direct `self.llm.settings.primary_model` read with guarded access
- File: `core/agent.py`
- Code: use `getattr(self.llm, "settings", None)` and then `getattr(..., "primary_model", "")`, defaulting to an empty string when unavailable.

**Step 4:** Run the focused agent tests
- Run: `python -m pytest tests/core/test_agent.py -q`
- Expected: all tests in `tests/core/test_agent.py` pass.

---

### Task 3: Re-verify the repository baseline

**Files:**
- Create/Modify: none unless a regression appears

**Step 1:** Run the fast stop-on-first-failure suite
- Run: `python -m pytest tests/ -x -q`
- Expected: no failures.

**Step 2:** Run the full suite
- Run: `python -m pytest tests/ -q`
- Expected: no failures and no expansion of the previous failure set.

**Step 3:** Review results before reporting completion
- Check: confirm the agent failures are gone, the LLM failures are gone, and no unrelated tests regressed.
