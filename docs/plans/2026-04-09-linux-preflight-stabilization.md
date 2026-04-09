# Linux Preflight Stabilization Implementation Plan

**Directive:** None present in `directives/` on 2026-04-09
**Date:** 2026-04-09
**Goal:** Close the remaining runtime and validation gaps before Ubuntu 24.04 smoke testing, update manual smoke documentation, and land the work on `main`.
**Architecture Notes:** The remaining failures are not feature gaps; they are preflight hardening items. `core/context_compressor.py` must propagate trace IDs into nested LLM calls, semantic skill routing should not rely on unsafe narrowing around optional embeddings, `memory/summarizer.py` should return only validated summary text, and the temporary pytest sandbox workaround must stop overriding Linux tempdir behavior.

---

### Task 1: Add RED tests for the remaining robustness gaps

**Files:**
- Create/Modify: `tests/core/test_context_compressor.py`
- Create/Modify: `tests/memory/test_summarizer.py`
- Create/Modify: `tests/skills/test_semantic_routing.py`

**Step 1:** Add a failing compressor test for trace propagation
- File: `tests/core/test_context_compressor.py`
- Code: assert `_summarise()` and `_merge()` pass `trace_id` through to `llm.generate(...)`, and that `compress()` can fall back to the current trace context when no explicit trace ID is provided.
- Run: `python -m pytest tests/core/test_context_compressor.py -q`
- Expected: at least one failure showing the missing `trace_id` kwarg.

**Step 2:** Add a failing summarizer test for malformed summary payloads
- File: `tests/memory/test_summarizer.py`
- Code: assert `get_session_summary()` returns `None` when the first search result has no string `text`.
- Run: `python -m pytest tests/memory/test_summarizer.py -q`
- Expected: the new test fails because the method currently returns unchecked data.

**Step 3:** Extend routing coverage only if needed
- File: `tests/skills/test_semantic_routing.py`
- Code: add a regression for optional embeddings only if the runtime fix changes observable behavior.
- Run: `python -m pytest tests/skills/test_semantic_routing.py -q`
- Expected: existing tests remain the baseline; new coverage only if it adds a real behavioral contract.

---

### Task 2: Implement the minimum runtime fixes

**Files:**
- Create/Modify: `core/context_compressor.py`
- Create/Modify: `core/agent.py`
- Create/Modify: `skills/registry.py`
- Create/Modify: `memory/summarizer.py`
- Create/Modify: `tests/conftest.py`

**Step 1:** Propagate trace IDs through the compressor
- File: `core/context_compressor.py`
- Code: add optional `trace_id` parameters to `compress()`, `_summarise()`, and `_merge()`. Use the explicit value when provided, otherwise fall back to `core.telemetry.get_trace_id()`.

**Step 2:** Pass the session trace explicitly from the agent
- File: `core/agent.py`
- Code: update the `ContextCompressor.compress(...)` call to pass the current `trace_id`.

**Step 3:** Remove unsafe optional narrowing in semantic routing
- File: `skills/registry.py`
- Code: guard `_cosine_similarity(...)` with an explicit `query_embedding is None` check inside `_score(...)`.

**Step 4:** Harden summary retrieval
- File: `memory/summarizer.py`
- Code: validate the retrieved `text` value before returning it; malformed payloads should return `None`.

**Step 5:** Make the pytest tempdir workaround Windows-only
- File: `tests/conftest.py`
- Code: only override environment temp dirs on Windows; on Linux and other non-Windows platforms, delegate to `tmp_path_factory`.

**Step 6:** Run the focused suites
- Run: `python -m pytest tests/core/test_context_compressor.py tests/memory/test_summarizer.py tests/skills/test_semantic_routing.py -q`
- Expected: all targeted tests pass.

---

### Task 3: Update smoke documentation

**Files:**
- Create/Modify: `TEST_PLAN.md`

**Step 1:** Add a Linux manual smoke section
- File: `TEST_PLAN.md`
- Code: document an Ubuntu 24.04 smoke pass covering startup, tool execution, semantic extraction, summarization/context compression, `USER.md` refresh after 10 turns, transcript search, and systemd restart behavior.

**Step 2:** Include exact commands and expected observations
- File: `TEST_PLAN.md`
- Code: keep the steps executable by an operator with a fresh Ubuntu host and local Ollama/Qdrant stack.

---

### Task 4: Verify and land

**Files:**
- Create/Modify: none unless verification exposes a regression

**Step 1:** Run targeted verification
- Run: `python -m pytest tests/core/test_context_compressor.py tests/memory/test_summarizer.py tests/skills/test_semantic_routing.py -q`
- Expected: all pass.

**Step 2:** Run full verification
- Run: `python -m pytest tests/ -x -q`
- Expected: no failures.
- Run: `python -m pytest tests/ -q`
- Expected: full suite passes.

**Step 3:** Run type and lint checks on the touched files
- Run: `python -m mypy core/context_compressor.py skills/registry.py memory/summarizer.py`
- Expected: no type errors.
- Run: `python -m ruff check core/context_compressor.py core/agent.py skills/registry.py memory/summarizer.py tests/core/test_context_compressor.py tests/memory/test_summarizer.py tests/skills/test_semantic_routing.py tests/conftest.py`
- Expected: all checks pass.

**Step 4:** Commit and merge
- Run: `git add ...`
- Run: `git commit -m "fix: finalize linux preflight stabilization"`
- Run: `git push origin feature/claw-gaps`
- Run: `git fetch origin main`
- Run: merge `feature/claw-gaps` into `main`, verify, then push `main`
- Expected: branch and main both contain the verified changes.
