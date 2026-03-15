# Directive 008: Skills & Tools Framework

## Objective
Build a structured, extensible framework for the agent to use tools/skills. This includes a decorator-based registration system, JSON schema generation for the LLM, and safe, sandboxed execution of python callbacks.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `skills/registry.py` (Tool registration and schema generation)
- `skills/executor.py` (Sandboxed/timed-out tool execution)
- `tests/skills/test_registry.py`
- `tests/skills/test_executor.py`

**OFF-LIMITS (Do NOT modify):**
- `core/*`
- `memory/*`
- `api/*`

## Acceptance Criteria
- [ ] Implement a `@skill(name, description)` decorator that registers Python async functions.
- [ ] Parse function signatures and docstrings to automatically generate standard JSON Schemas for LiteLLM/OpenAI tool calling formats.
- [ ] Implement `SkillExecutor.execute(name, kwargs)` that runs the tool safely.
- [ ] Wrap skill execution in a hard timeout (e.g., `asyncio.wait_for`).
- [ ] Emit `TOOL_INVOKE`, `TOOL_COMPLETE`, and `TOOL_ERROR` telemetry events.
- [ ] TDD all parsing and execution paths with comprehensive unit tests in `tests/skills/`.

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
