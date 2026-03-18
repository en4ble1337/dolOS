# AGENTS.md - System Kernel

## Project Context

**Name:** dolOS
**Purpose:** Custom AI agent system based on OpenClaw architecture, optimized for local-first operation with Ollama on RTX 5090.
**Stack:** Python 3.11+, FastAPI, Ollama, LiteLLM, Qdrant, sentence-transformers, APScheduler

## Core Domain Entities

- Agent: Core orchestrator managing LLM interactions and memory
- Memory: Vector and keyword searchable storage of past interactions and facts
- Channel: Interface for communicating with the agent (Telegram, Discord, Terminal)
- Tool/Skill: Actions the agent can perform
- Heartbeat: Proactive scheduled tasks

---

## 1. The Prime Directive

You are an agent operating on the dolOS codebase.

**Before writing ANY code:**
1. Read `README.md` to understand the architecture and file structure
2. Consult `docs/features-assessment.md` for the current feature plan
3. Check `directives/` for your current assignment

**Core Rules:**
- Use ONLY the technologies defined in the Tech Stack
- Place code ONLY in the directories specified in the README Project Structure
- **CRITICAL:** Any significant architectural changes, massive refactors, or actions that could 'nuke' or drastically alter the app's functionality must be explicitly confirmed with the user prior to execution. Do not make autonomous changes of this scale.

---

## 2. The 3-Layer Workflow

### Layer 1: Directives (Orders)
- Location: `directives/`
- Purpose: Task assignments with specific acceptance criteria
- Action: Read the lowest-numbered incomplete directive

### Layer 2: Orchestration (Planning)
- Location: `docs/plans/`
- Purpose: Granular implementation plans for each directive
- Action: Before coding, break the directive into tasks following `docs/methodology/implementation-planning.md`

### Layer 3: Execution (Automation)
- Location: `scripts/` (or `execution/`)
- Purpose: Reusable scripts for repetitive tasks

---

## 3. The TDD Iron Law

**NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.**

### The Mandatory Cycle

For every piece of functionality:

1. **RED:** Write a test in `tests/` that describes the expected behavior. Run it. Confirm it **fails** — and fails for the *right reason* (assertion failure, not import error).
2. **GREEN:** Write the **minimum** code in `core/`, `api/`, etc., to make the test pass. Run all tests. Confirm they **all pass**.
3. **REFACTOR:** Clean up the code while keeping tests green. Run all tests again. Confirm they still pass.
4. **COMMIT:** Only after all tests pass.

### The Nuclear Rule

If you write production code before writing its test:
- **Delete it.** Not "keep as reference." Not "adapt it while writing tests." Delete means delete.
- Write the test first.
- Implement fresh, guided by the failing test.

### Test File Locations

Mirror the source structure:
- `core/agent.py` → `tests/core/test_agent.py`
- `memory/vector_store.py` → `tests/memory/test_vector_store.py`

### TDD Rationalizations Table

If you catch yourself thinking any of these, **STOP**:

| Excuse | Reality |
|--------|---------|
| "This is too simple to test" | Simple code breaks. The test takes 30 seconds to write. |
| "I'll write tests after" | Tests that pass immediately prove nothing — they describe what the code *does*, not what it *should* do. |
| "I already tested it manually" | Manual testing has no record and can't be re-run. |
| "Deleting my work is wasteful" | Sunk cost fallacy. Keeping unverified code is technical debt with interest. |
| "I'll keep it as reference and write tests first" | You'll adapt it. That's tests-after with extra steps. Delete means delete. |
| "I need to explore first" | Explore freely. Then throw away the exploration and start with TDD. |
| "The test is hard to write — the design isn't clear yet" | Listen to the test. Hard to test = hard to use. Redesign. |
| "TDD will slow me down" | TDD is faster than debugging. Every shortcut becomes a debugging session. |
| "TDD is dogmatic; I'm being pragmatic" | TDD IS pragmatic. "Pragmatic" shortcuts = debugging in production. |
| "This is different because..." | It's not. Delete the code. Start with the test. |

### Red Flags — Stop and Start Over

- You wrote code before its test
- A new test passes immediately (you're testing what already exists, not defining behavior)
- You can't explain why a test failed
- You're rationalizing "just this once"

---

## 4. Implementation Planning

**Before coding any directive, create an implementation plan.**

See `docs/methodology/implementation-planning.md` for the full template.

**The rule:** Write every plan as if the implementer is an enthusiastic junior engineer with no project context and an aversion to testing. This forces you to be completely explicit:

- **Exact file paths** — not "the config file" but `config/settings.yaml`
- **Complete code** — not "add validation" but the actual validation code
- **Exact commands** — not "run the tests" but `pytest tests/core/test_agent.py -v`
- **Expected output** — what success/failure looks like

**Granularity:** Each task should take 2-5 minutes. Each step within a task is exactly ONE action.

Plans are saved to `docs/plans/YYYY-MM-DD-<feature-name>.md`.

---

## 5. Review Gates

**Every completed task goes through two review stages before moving on.**

See `docs/methodology/review-gates.md` for checklists.

### Gate 1: Spec Compliance Review
After completing a task, review against the directive's acceptance criteria:
- Does the code implement exactly what was specified?
- Is anything **missing** from the spec?
- Is anything **extra** that wasn't requested? (Remove it.)
- **Do not trust self-reports.** Read the actual code. Run the actual tests.

### Gate 2: Code Quality Review
Only after spec compliance passes:
- Architecture: Does it follow expected patterns?
- Testing: Are tests meaningful (not just asserting mock behavior)?
- DRY: Is there duplication that should be consolidated?
- Error handling: Are failure modes covered?

Issues are categorized:
- **Critical** — Must fix before proceeding. Blocks progress.
- **Important** — Should fix. Creates tech debt if skipped.
- **Minor** — Nice to have. Fix if time allows.

### Batch Checkpoints
After every 3 completed tasks, pause and produce a progress report:
- What's been completed
- What's next
- Any concerns or architectural questions
- Request human feedback before continuing

---

## 6. Verification Before Completion

**NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE.**

Before marking any task, directive, or feature as "done":
1. **Run the verification command** (test suite, linter, type checker)
2. **Read the actual output** — not from memory, not assumed
3. **Include the evidence** in your completion report

### Verification Red Flags — Stop Immediately

If you catch yourself using these words before running verification:
- "Should work now"
- "That should fix it"
- "Seems correct"
- "I'm confident this works"
- "Great! Done!"

These are emotional signals, not evidence. **Run the command. Read the output. Then speak.**

### Verification Rationalizations Table

| Excuse | Reality |
|--------|---------|
| "It should work now" | Run the verification. |
| "I'm confident in this change" | Confidence is not evidence. |
| "The linter passed" | Linter passing ≠ tests passing ≠ correct behavior. |
| "I checked it mentally" | Mental checks miss edge cases. Run the actual command. |
| "Just this once we can skip verification" | No exceptions. |
| "Partial verification is enough" | Partial evidence proves nothing about what you didn't check. |

---

## 7. Systematic Debugging

**NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**

When something breaks, follow the 4-phase process. See `docs/methodology/debugging-guide.md` for details.

### Phase 1: Root Cause Investigation
- Read the error carefully. Reproduce it consistently.
- Check what recently changed.
- Trace the data flow backward from the symptom to the source.

### Phase 2: Pattern Analysis
- Find working examples of similar code in the codebase.
- Compare the broken code against working references.
- Identify all differences.

### Phase 3: Hypothesis and Testing
- Form ONE hypothesis: "I think X happens because Y."
- Test with the smallest possible change.
- If wrong, form a NEW hypothesis. Do not stack fixes.

### Phase 4: Implementation
- Write a failing test that reproduces the bug.
- Fix with a single, targeted change.
- Verify all tests pass (existing + new).

### The 3-Strikes Rule
If 3 consecutive fix attempts fail: **STOP.**
- Question whether the approach or architecture is fundamentally sound.
- Discuss with the team before attempting more fixes.
- Consider whether you're fixing a symptom instead of the cause.

---

## 8. Anti-Rationalization Rules

AI agents (including you) will try to bypass the processes above. This section preemptively blocks the most common escape routes.

**The principle: The ritual IS the spirit.** Violating the letter of these rules is violating the spirit. There are no clever workarounds.

### Universal Red Flags

If any of these thoughts arise, treat them as a signal to **slow down**, not speed up:

- "I need more context before I can start" — You have the directives and config. Start with the test.
- "Let me explore the codebase first" — Read the plan. If there's no plan, write one. Don't explore aimlessly.
- "I'll clean this up later" — Clean it up now or don't touch it.
- "This doesn't apply to this situation" — It does. Follow the process.
- "I already know the answer" — Prove it. Write the test. Run the verification.
- "I'll be more careful next time" — Be careful this time. Follow the process this time.

---

## 9. Definition of Done

A task is complete when:
- [ ] Implementation plan was written before coding
- [ ] Code exists in appropriate subdirectory
- [ ] All new code has corresponding tests in `tests/`
- [ ] Tests were written BEFORE implementation (TDD)
- [ ] All tests pass (verified by running them, output confirmed)
- [ ] Type checking passes (`mypy`)
- [ ] Linting passes (`ruff`, `black`)
- [ ] Spec compliance review passed (code matches directive acceptance criteria)
- [ ] Code quality review passed (no Critical or Important issues)
- [ ] Directive file is marked as Complete

---

## 10. File Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Python modules | snake_case | `vector_store.py` |
| Python classes | PascalCase | `class VectorStore` |
| Test files | `test_` prefix | `test_vector_store.py` |
| Directives | `NNN_description.md` | `001_observability_backend.md` |
| Implementation plans | `YYYY-MM-DD-feature.md` | `2026-03-13-observability.md` |
