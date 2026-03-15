# Implementation Plan: Directive 009 - Proactive Heartbeat System

## Overview
Implement the `HeartbeatSystem` using `APScheduler` (specifically `AsyncIOScheduler`) in `core/heartbeat.py`. It will run scheduled proactive health and reflection tasks in the background, emitting telemetry for every job.

## Steps

### Task 1: Scaffolding and Tests (RED)
- **Path**: `tests/core/test_heartbeat.py`
- **Code**:
  - Test scheduler starting and shutting down.
  - Test registration of background tasks (e.g. self-reflection and health check).
  - Test the actual execution wrapper to ensure `HEARTBEAT_START` and `HEARTBEAT_COMPLETE` events are emitted.
- **Command**: `pytest tests/core/test_heartbeat.py -v`
- **Expected Output**: Failing tests.

### Task 2: Core Implementation (GREEN)
- **Path**: `core/heartbeat.py`
- **Code**:
  - Create `HeartbeatSystem` wrapping `AsyncIOScheduler`.
  - Implement `.start()` and `.shutdown()`.
  - Implement `.register_task(name, func, trigger=...)`.
  - Wrap task executions to capture telemetry and trace IDs cleanly during the background job.
  - Implement default `health_check` and `self_reflection` task stumps.
- **Command**: `pytest tests/core/test_heartbeat.py -v`
- **Expected Output**: Passing tests.

### Task 3: Refactor & Lints (REFACTOR)
- **Code**: Clean up typing and dependencies. Ensure `apscheduler` is imported cleanly.
- **Command**: `ruff check core/heartbeat.py tests/core/test_heartbeat.py && mypy core/heartbeat.py tests/core/test_heartbeat.py`
- **Expected Output**: Clean linters.
