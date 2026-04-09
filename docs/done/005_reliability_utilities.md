# Directive 005: Reliability Utilities

## Objective
Build the core reliability primitives: Circuit Breakers and Retry strategies. These utilities will wrap external API calls (Ollama, Qdrant, etc.) to prevent cascading failures and handle transient network issues smoothly.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `core/reliability.py` (Circuit breaker and retry implementations)
- `tests/core/test_reliability.py`

**OFF-LIMITS (Do NOT modify):**
- `core/llm.py`
- `core/telemetry.py` (You may IMPORT it to emit `CIRCUIT_OPEN` events, but do not change it)
- `memory/*`
- `api/*`

## Acceptance Criteria
- [x] Implement an asynchronous `retry_with_backoff` decorator in `core/reliability.py` supporting exponential backoff, jitter, and max attempts.
- [x] Implement an asynchronous `CircuitBreaker` class in `core/reliability.py` using a standard state machine (Closed, Open, Half-Open).
- [x] The CircuitBreaker should track failure thresholds and reset timeouts.
- [x] When a circuit trips from Closed to Open, it must emit a `CIRCUIT_OPEN` telemetry event.
- [x] These must be purely generic utilities (they should not import `core.llm` or `memory`; rather, those modules will eventually import `reliability`).
- [x] Comprehensive unit tests verifying backoff timings, state transitions, and exception propagation in `tests/core/test_reliability.py`.

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
