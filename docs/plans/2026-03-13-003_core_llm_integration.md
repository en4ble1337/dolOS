# Implementation Plan: Directive 003 Core LLM Integration

## Task 1: Configuration Layer (core/config.py)
**Description:** Create `core/config.py` using `pydantic-settings` to load model names and API keys.
1. Write tests in `tests/core/test_config.py`.
2. Implement `Settings` class in `core/config.py`.
3. Verify with `pytest tests/core/test_config.py -v`.

## Task 2: LLM Gateway Tests (tests/core/test_llm.py)
**Description:** Write tests for the `LLMGateway` class in `core/llm.py` before implementation.
1. Mock `litellm.acompletion` to simulate success and failure.
2. Test standard message generation.
3. Test fallback mechanism on Ollama failure.
4. Test telemetry emission (`LLM_CALL_START`, `LLM_CALL_END`, `LLM_FALLBACK`).
5. Run tests to confirm they fail (RED phase).

## Task 3: LLM Gateway Implementation (core/llm.py)
**Description:** Implement `LLMGateway` utilizing `litellm.acompletion`.
1. Initialize with `EventBus` and `Settings`.
2. Implement `generate(messages, tools, trace_id)` method.
3. Add fallback logic when primary model fails.
4. Emit telemetry events.
5. Run `pytest tests/core/test_llm.py -v` (GREEN phase).
6. Refactor if needed.
7. Run linting (`ruff check .`, `black .`, `mypy core api`).
