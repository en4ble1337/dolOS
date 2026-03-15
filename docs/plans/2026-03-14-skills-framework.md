# Implementation Plan: Directive 008 - Skills & Tools Framework

## Overview
We need to give the agent an extensible skill framework. We will implement `@skill(name, description)` decorator and `SkillExecutor.execute()`. These live in the new `skills` module. 

## Steps
### Task 1: Scaffolding and Tests (RED)
- **Path**: `tests/skills/test_registry.py` and `tests/skills/test_executor.py`
- **Code**:
  - `test_registry.py`: We'll define a couple of fake skills (one simple, one with args) decorated with `@skill`. We'll assert that `SkillRegistry.get_schema("skill_name")` returns valid JSON schemas matching OpenAI format.
  - `test_executor.py`: We'll test `SkillExecutor.execute("skill_name", {"arg": "val"})`. We will test successful execution, a thrown exception yielding `TOOL_ERROR`, and an `asyncio.TimeoutError` triggering after 5 seconds.
- **Command**: `pytest tests/skills/ -v`
- **Expected Output**: Failing tests.

### Task 2: Implement Skills Framework (GREEN)
- **Path**: `skills/__init__.py`, `skills/registry.py`, `skills/executor.py`
- **Code**:
  - `registry.py`: `SkillRegistry` class (singleton or dependency injected). Implement `register` method and `@skill` decorator. Use `inspect` and type hints to infer Pydantic schemas or raw JSON schemas.
  - `executor.py`: `SkillExecutor` receives the `EventBus`. It resolves a skill by name using the `SkillRegistry`, runs `asyncio.wait_for(skill(**kwargs), timeout)`, and catches errors, emitting `TOOL_INVOKE`, `TOOL_COMPLETE`, `TOOL_ERROR` telemetry events.
- **Command**: `pytest tests/skills/ -v`
- **Expected Output**: Passing tests.

### Task 3: Refactor & Lints (REFACTOR)
- **Code**: Validate correct typing.
- **Command**: `ruff check skills/ tests/skills/` and `mypy skills/ tests/skills/`
- **Expected Output**: Clean linters.
