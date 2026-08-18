# Safety Hardening Implementation Plan

**Directive:** Ad hoc user request from cold review gap analysis
**Date:** 2026-05-03
**Goal:** Fix the concrete high-confidence security and correctness gaps found in generated skills, skill extraction, sandbox path checks, and context reference expansion.
**Architecture Notes:** Keep changes scoped to existing modules and tests. Use the existing skill registry, sandbox executor, and context-ref APIs. Do not introduce OS-level sandboxing or structured plan approval in this pass because those are larger architectural changes that need a separate directive.

---

### Task 1: Generated Skill Name Validation

**Files:**
- Modify: `skills/local/meta.py`
- Modify: `skills/executor.py`
- Modify: `tests/skills/test_skill_auto_fix.py`

**Step 1:** Write failing tests
- File: `tests/skills/test_skill_auto_fix.py`
- Add tests that:
  - `create_skill(name="../escape", ...)` returns an error and writes no escaped file.
  - `create_skill(name="Bad-Name", ...)` returns an error.
  - `fix_skill("../escape")` returns an error without reading outside `generated/`.
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py -q`
- Expected: the new tests fail because invalid names are currently accepted as path components.

**Step 2:** Implement minimum code
- File: `skills/local/meta.py`
- Add:
  ```python
  _SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

  def _validate_generated_skill_name(name: str) -> str | None:
      if not _SKILL_NAME_RE.fullmatch(name):
          return (
              "Error: Invalid generated skill name. Use snake_case matching "
              "^[a-z][a-z0-9_]*$."
          )
      return None
  ```
- Call the helper at the top of `create_skill()` and `fix_skill()`.
- File: `skills/executor.py`
- Import and use `_validate_generated_skill_name()` in `_is_generated_skill()` so generated-skill detection never constructs paths from invalid names.
- Run: `python -m pytest tests/skills/test_skill_auto_fix.py -q`
- Expected: all tests in the file pass.

**Step 3:** Review
- Confirm path construction only happens after name validation.
- Confirm no unrelated generated skill behavior changed.

---

### Task 2: Strict Skill Extraction JSON Booleans

**Files:**
- Modify: `memory/skill_extractor.py`
- Modify: `tests/memory/test_skill_extractor.py`

**Step 1:** Write failing tests
- File: `tests/memory/test_skill_extractor.py`
- Add tests that:
  - LLM JSON with `"is_read_only": "false"` is rejected and does not call `create_skill`.
  - LLM JSON with `"concurrency_safe": "true"` is rejected and does not call `create_skill`.
- Run: `python -m pytest tests/memory/test_skill_extractor.py -q`
- Expected: the new tests fail because Python currently coerces non-empty strings to `True`.

**Step 2:** Implement minimum code
- File: `memory/skill_extractor.py`
- Add a small Pydantic model with strict boolean fields:
  ```python
  class SkillExtractionDecision(BaseModel):
      should_create: bool
      reason: str = ""
      name: str = ""
      description: str = ""
      code: str = ""
      is_read_only: bool = False
      concurrency_safe: bool = False

      model_config = ConfigDict(strict=True)
  ```
- Parse the JSON dict through this model and emit `SKILL_EXTRACTION_ERROR` on validation failure.
- Run: `python -m pytest tests/memory/test_skill_extractor.py -q`
- Expected: all tests in the file pass.

**Step 3:** Review
- Confirm only real JSON booleans are accepted.
- Confirm existing valid extraction tests still pass.

---

### Task 3: Sandbox Python Wrapper Path Enforcement

**Files:**
- Modify: `skills/sandbox.py`
- Modify: `tests/skills/test_sandbox.py`

**Step 1:** Write failing tests
- File: `tests/skills/test_sandbox.py`
- Add tests that:
  - `validate_path_access()` denies a sibling path whose string prefix matches an allowed directory.
  - `execute_code()` denies `open()` on a sibling path such as `allowed_sneaky/file.txt` when allowed root is `allowed`.
- Run: `python -m pytest tests/skills/test_sandbox.py -q`
- Expected: the wrapper test fails because `_sandboxed_open()` uses string prefix matching.

**Step 2:** Implement minimum code
- File: `skills/sandbox.py`
- In `_build_sandbox_env()` and `_build_code_wrapper()`, use resolved paths.
- Replace wrapper `startswith()` logic with:
  ```python
  resolved = _Path(file).resolve()
  for allowed in _allowed_paths:
      try:
          if resolved.is_relative_to(_Path(allowed).resolve()):
              return _original_open(file, mode, *args, **kwargs)
      except (ValueError, OSError):
          continue
  ```
- Run: `python -m pytest tests/skills/test_sandbox.py -q`
- Expected: all tests in the file pass.

**Step 3:** Review
- Confirm wrapper behavior now matches `validate_path_access()`.
- Confirm shell command behavior is not represented as fixed; shell policy remains a separate larger task.

---

### Task 4: Bounded and Tainted Context Reference Expansion

**Files:**
- Modify: `core/context_refs.py`
- Modify: `tests/core/test_context_refs.py`

**Step 1:** Write failing tests
- File: `tests/core/test_context_refs.py`
- Add tests that:
  - Folder expansion stops during traversal once a caller-provided byte/char budget is reached.
  - Expanded file, folder, and URL content include an explicit untrusted-data boundary.
- Run: `python -m pytest tests/core/test_context_refs.py -q`
- Expected: the new tests fail because folder traversal currently reads everything before aggregate limit enforcement and boundaries are not present.

**Step 2:** Implement minimum code
- File: `core/context_refs.py`
- Add an untrusted content marker constant.
- Pass a remaining character budget into `_read_folder()` and stop reading before content exceeds it.
- Wrap file, folder, git, diff, and URL expansions with the untrusted boundary.
- Run: `python -m pytest tests/core/test_context_refs.py -q`
- Expected: all tests in the file pass.

**Step 3:** Review
- Confirm limits are enforced during folder traversal.
- Confirm existing context-ref syntax stays compatible.

---

### Final Verification

**Run targeted tests:**
`python -m pytest tests/skills/test_skill_auto_fix.py tests/memory/test_skill_extractor.py tests/skills/test_sandbox.py tests/core/test_context_refs.py -q`

**Run formatting and linting:**
`python -m black skills/local/meta.py skills/executor.py memory/skill_extractor.py skills/sandbox.py core/context_refs.py tests/skills/test_skill_auto_fix.py tests/memory/test_skill_extractor.py tests/skills/test_sandbox.py tests/core/test_context_refs.py`

`python -m ruff check skills/local/meta.py skills/executor.py memory/skill_extractor.py skills/sandbox.py core/context_refs.py tests/skills/test_skill_auto_fix.py tests/memory/test_skill_extractor.py tests/skills/test_sandbox.py tests/core/test_context_refs.py`

**Expected:** targeted tests pass and linting reports no errors.
