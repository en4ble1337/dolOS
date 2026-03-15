import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.heartbeat import HeartbeatSystem
from core.telemetry import EventBus, EventType


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


@pytest.mark.asyncio
async def test_heartbeat_startup_shutdown(mock_event_bus: EventBus) -> None:
    system = HeartbeatSystem(event_bus=mock_event_bus)
    system.start()
    assert system.is_running() is True

    system.shutdown()
    assert system.is_running() is False


@pytest.mark.asyncio
async def test_heartbeat_task_execution_telemetry(mock_event_bus: EventBus) -> None:
    system = HeartbeatSystem(event_bus=mock_event_bus)
    system.start()

    dummy_task = AsyncMock(return_value="Action Complete")

    # Registering a task to run immediately/once just for the test
    # apscheduler date trigger runs once at a specific time, default now
    system.register_task("dummy_check", dummy_task, trigger="date")

    # Yield control to the event loop so apscheduler runs the job
    await asyncio.sleep(0.1)

    system.shutdown()

    # Task should be called
    dummy_task.assert_called_once()

    # Ensure telemetry matches expectations
    emitted_types = [
        call.args[0].event_type
        for call in mock_event_bus.emit.await_args_list  # type: ignore[attr-defined]
    ]

    assert EventType.HEARTBEAT_START in emitted_types
    assert EventType.HEARTBEAT_COMPLETE in emitted_types

    # Find complete event
    complete_events = [
        call.args[0]
        for call in mock_event_bus.emit.await_args_list  # type: ignore[attr-defined]
        if call.args[0].event_type == EventType.HEARTBEAT_COMPLETE
    ]

    assert len(complete_events) == 1
    assert complete_events[0].payload["job_name"] == "dummy_check"
    assert "error" not in complete_events[0].payload


@pytest.mark.asyncio
async def test_heartbeat_task_error(mock_event_bus: EventBus) -> None:
    system = HeartbeatSystem(event_bus=mock_event_bus)
    system.start()

    broken_task = AsyncMock(side_effect=ValueError("Database offline!"))

    system.register_task("failing_check", broken_task, trigger="date")

    await asyncio.sleep(0.1)
    system.shutdown()

    broken_task.assert_called_once()

    emitted_types = [
        call.args[0].event_type
        for call in mock_event_bus.emit.await_args_list  # type: ignore[attr-defined]
    ]

    assert EventType.HEARTBEAT_START in emitted_types

    error_events = [
        call.args[0]
        for call in mock_event_bus.emit.await_args_list  # type: ignore[attr-defined]
        if call.args[0].event_type == EventType.HEARTBEAT_COMPLETE
    ]

    # In my specification, I usually expect a HEARTBEAT_COMPLETE with an error payload
    # or an explicit error telemetry event. Let's look for error string in payload
    has_error = any(
        "error" in event.payload or event.success is False
        for event in error_events
    )
    assert has_error
