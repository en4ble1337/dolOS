# Implementation Planning Guide

## Purpose

Before coding any directive, break it into a detailed implementation plan. This prevents "context drift" (gradually forgetting the architecture during long coding sessions) and ensures each step is small enough to verify independently.

## Plan Template

Save plans to `docs/plans/YYYY-MM-DD-<feature-name>.md`.

```markdown
# [Feature Name] Implementation Plan

**Directive:** [NNN]
**Date:** [YYYY-MM-DD]
**Goal:** [One sentence — what this achieves]
**Architecture Notes:** [2-3 sentences — key patterns that apply]

---

### Task 1: [Component Name]

**Files:**
- Create/Modify: `path/to/file.py`
- Create/Modify: `tests/path/test_file.py`

**Step 1:** Write failing test
- File: `tests/path/test_file.py`
- Code: [complete test code]
- Run: `pytest tests/path/test_file.py -v`
- Expected: 1 failed (test_name)

**Step 2:** Implement minimum code
- File: `path/to/file.py`
- Code: [complete implementation code]
- Run: `pytest tests/path/test_file.py -v`
- Expected: 1 passed

**Step 3:** Refactor (if needed)
- [Describe what to clean up]
- Run: `pytest tests/ -v`
- Expected: All passed

**Step 4:** Commit
- `git add path/to/file.py tests/path/test_file.py`
- `git commit -m "feat(scope): context"`
```

## Task Decomposition Rules

1. **2-5 minutes per task.** If a task takes longer, break it down further.
2. **One action per step.** "Write the test" is one step. "Run the test" is a separate step.
3. **Exact file paths.** Never say "the config file" — say `config/settings.yaml`.
4. **Complete code.** Never say "add validation" — write the actual validation code.
5. **Exact commands with expected output.** Never say "run tests" — say `pytest tests/core/test_agent.py -v` and describe what success looks like.
6. **Write for someone with no context.** Assume the implementer cannot infer anything. Be painfully explicit.

## Plan Execution

Execute tasks sequentially. After each task:
1. Run the spec compliance review (does it match the directive?)
2. Run the code quality review (is it well-built?)
3. Move to the next task only when both reviews pass.

After every 3 tasks, produce a checkpoint report.
