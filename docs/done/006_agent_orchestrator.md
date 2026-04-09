# Directive 006: Agent Orchestrator

## Objective
Build the central `Agent` class that wires together the LLM Gateway, Memory System, Telemetry, and Reliability modules into a cohesive orchestration layer. The Agent will handle the main request-response cycle: receive prompt, retrieve context, format prompt, call LLM, and store response.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `core/agent.py` (The main Agent orchestrator)
- `tests/core/test_agent.py`

**OFF-LIMITS (Do NOT modify):**
- `core/llm.py`
- `core/telemetry.py`
- `core/reliability.py`
- `memory/*`
- `channels/*`

## Acceptance Criteria
- [x] Create `core/agent.py` with an `Agent` class that takes instances of `LLMGateway`, `MemoryManager`, and `EventBus` via dependency injection.
- [x] Implement an async `process_message(session_id: str, message: str) -> str` method.
- [x] Inside `process_message`:
  1. Generate a new trace ID and set it via `set_trace_id()`.
  2. Query episodic memory for recent context.
  3. Query semantic memory for relevant facts.
  4. Call the LLM Gateway with the constructed context + message.
  5. Save the user message and assistant reply to episodic memory.
- [x] Wrap external memory and LLM calls with Circuit Breakers and retries from `core/reliability.py`.
- [x] Emit high-level trace events starting and ending the request.
- [x] All code must have corresponding tests in `tests/core/test_agent.py` (mocking the injected dependencies).

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
