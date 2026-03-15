# Implementation Plan: 2026-03-13-observability-phase-b

## Objective
Implement Directive 002: Observability Phase B. This includes an in-memory RingBuffer, trace ID propagation via `contextvars`, background metrics aggregation, and FastAPI endpoints (REST + WebSocket) for the dashboard.

## Proposed Changes

### Core Telemetry (`core/telemetry.py`)
- Add `RingBuffer` class using `collections.deque`.
- Implement `get_trace_id()` and `set_trace_id()` using `contextvars.ContextVar`.
- Update `EventCollector` to:
    - Hold a `RingBuffer` instance.
    - Push events to the buffer in `write_event`.
    - Provide a method to retrieve recent events from the buffer.
- Add a metrics aggregation task that runs periodically to calculate events per minute and write to the `metrics` table.

### API Layer
- Create `api/websocket.py` with a `ConnectionManager` to handle multiple WebSocket clients and broadcasting.
- Create `api/routes/observability.py`:
    - `GET /events/recent`: Returns events from the `EventCollector`'s ring buffer.
    - `WS /events/live`: WebSocket endpoint for real-time event streaming.

## Step-by-Step Execution Plan

### Task 1: Trace ID Propagation (TDD)
1. **RED**: Create `tests/core/test_telemetry_trace.py` (or add to existing) testing that `get_trace_id` returns a default when unset and the correct value after `set_trace_id`.
2. **GREEN**: Implement `trace_id` `ContextVar`, `get_trace_id`, and `set_trace_id` in `core/telemetry.py`.
3. **REFACTOR**: Ensure clean integration.
4. **VERIFY**: `pytest tests/core/test_telemetry.py`

### Task 2: RingBuffer Implementation (TDD)
1. **RED**: Write tests for `RingBuffer` in `tests/core/test_telemetry.py` (append, size limit, retrieving all).
2. **GREEN**: Implement `RingBuffer` in `core/telemetry.py`.
3. **REFACTOR**: Optimize if necessary.
4. **VERIFY**: `pytest tests/core/test_telemetry.py`

### Task 3: Integrating RingBuffer with EventCollector (TDD)
1. **RED**: Update `tests/core/test_telemetry.py` to verify `EventCollector` stores events in its buffer.
2. **GREEN**: Update `EventCollector` in `core/telemetry.py` to use `RingBuffer`.
3. **VERIFY**: `pytest tests/core/test_telemetry.py`

### Task 4: Metrics Aggregation Task (TDD)
1. **RED**: Write test in `tests/core/test_telemetry_metrics.py` for the aggregation logic (mocking time and DB).
2. **GREEN**: Implement the background task in `core/telemetry.py`.
3. **VERIFY**: `pytest tests/core/test_telemetry_metrics.py`

### Task 5: WebSocket Connection Manager (TDD)
1. **RED**: Create `tests/api/test_websocket.py` testing connection, disconnection, and broadcasting.
2. **GREEN**: Create `api/websocket.py` with `ConnectionManager`.
3. **VERIFY**: `pytest tests/api/test_websocket.py`

### Task 6: REST and WebSocket Endpoints (TDD)
1. **RED**: Create `tests/api/test_observability_api.py` testing `GET /events/recent` and the WebSocket connection.
2. **GREEN**: Create `api/routes/observability.py` and register in the main app (if applicable/found).
3. **VERIFY**: `pytest tests/api/test_observability_api.py`

## Review Gates
- **Gate 1 (Spec Compliance)**: Check against Directive 002 criteria.
- **Gate 2 (Code Quality)**: Ensure TDD adherence and no redundant code.
