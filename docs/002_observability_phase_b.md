# Directive 002: Observability Phase B (Live Feed & Metrics)

## Objective
Extend the observability layer built in Directive 001. Implement an in-memory ring buffer for the live event feed, a background task for metrics aggregation, and FastAPI endpoints (WebSocket + REST) to expose this data to the dashboard. Trace ID propagation via `contextvars` is also included here to complete the telemetry foundation.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `core/telemetry.py` (adding RingBuffer, metrics aggregation task, and trace ID contextvars)
- `api/routes/observability.py` (REST and WebSocket endpoints)
- `api/websocket.py` (WebSocket connection manager)
- `tests/core/test_telemetry.py`
- `tests/api/test_observability.py`

**OFF-LIMITS (Do NOT modify):**
- `core/llm.py`
- `core/reliability.py`
- `memory/*`
- `pyproject.toml` / `requirements.txt` (unless adding specific required deps like `websockets`)

## Acceptance Criteria
- [x] Implement an in-memory `RingBuffer` (using `collections.deque`) in `core/telemetry.py` to hold the last 1000 events.
- [x] Wire the `EventCollector` to push events into the `RingBuffer` as well as SQLite.
- [x] Implement a `contextvars`-based trace ID propagation mechanism in `core/telemetry.py` (e.g., `set_trace_id()`, `get_trace_id()`).
- [x] Implement a background task (asyncio loop) that calculates aggregates (e.g., events per minute) and writes to the `metrics` table.
- [x] Create `api/routes/observability.py` with a REST endpoint `GET /events/recent` returning the ring buffer contents.
- [x] Create a WebSocket endpoint `ws /events/live` in `api/routes/observability.py` that broadcasts new events in real-time.
- [x] All code must have corresponding tests in `tests/` following the TDD methodology.
- [x] Documentation updated if needed.

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
