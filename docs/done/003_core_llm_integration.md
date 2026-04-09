# Directive 003: Core LLM Integration

## Objective
Implement the core LLM communication layer using `litellm`. The system uses a primary local engine (Ollama) with fallback capability to cloud models (e.g., GPT-4, Claude). This directive focuses purely on text generation, tool calling formats, and the fallback logic.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `core/llm.py` (LLM gateway and fallback logic)
- `core/config.py` (Model configuration and API keys)
- `tests/core/test_llm.py`
- `tests/core/test_config.py`

**OFF-LIMITS (Do NOT modify):**
- `core/telemetry.py` (You may IMPORT `EventBus` and emit events, but do not change its implementation)
- `memory/*`
- `api/*`

## Acceptance Criteria
- [x] Create `core/config.py` with `pydantic-settings` to load model names and API keys from environment variables/`.env`.
- [x] Implement the `LLMGateway` class in `core/llm.py` wrapping `litellm.acompletion`.
- [x] The `LLMGateway` must support standard `messages` generation.
- [x] Implement a fallback mechanism: if Ollama fails or times out, seamlessly retry with a secondary model (e.g., OpenAI or Anthropic).
- [x] Emit specific telemetry events (e.g., `LLM_CALL_START`, `LLM_CALL_END`, `LLM_FALLBACK`) using the observability layer built in Directive 001.
- [x] Ensure strict typing for tool definitions passed to the LLM.
- [x] All code must be driven by tests (mocking `litellm` where necessary).

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
