import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.telemetry import EventBus, EventType
from skills.executor import SkillExecutor
from skills.registry import SkillRegistry, skill


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


@pytest.fixture
def test_registry() -> SkillRegistry:
    reg = SkillRegistry()

    @skill(name="echo", registry=reg)
    def echo_skill(message: str) -> str:
        return message

    @skill(name="long_running", registry=reg)
    async def long_running_skill() -> str:
        await asyncio.sleep(2)
        return "done"

    @skill(name="broken_skill", registry=reg)
    def broken_skill() -> str:
        raise ValueError("I am broken")

    return reg


class TestSkillExecutor:
    @pytest.mark.asyncio
    async def test_successful_execution(
        self, test_registry: SkillRegistry, mock_event_bus: EventBus
    ) -> None:
        """Test that a skill executes correctly and emits success telemetry."""
        executor = SkillExecutor(registry=test_registry, event_bus=mock_event_bus)

        result = await executor.execute("echo", {"message": "hello world"}, trace_id="trace-123")
        assert result == "hello world"

        emitted = [
            call.args[0].event_type
            for call in mock_event_bus.emit.await_args_list  # type: ignore[attr-defined]
        ]
        assert EventType.TOOL_INVOKE in emitted
        assert EventType.TOOL_COMPLETE in emitted

        # Verify TOOL_INVOKE payload contains function name and args
        invoke_event = mock_event_bus.emit.await_args_list[0].args[0]  # type: ignore[attr-defined]
        assert invoke_event.payload["tool_name"] == "echo"
        assert invoke_event.payload["kwargs"] == {"message": "hello world"}

    @pytest.mark.asyncio
    async def test_timeout_execution(
        self, test_registry: SkillRegistry, mock_event_bus: EventBus
    ) -> None:
        """Test that a skill exceeding timeout is cancelled and emits an error event."""
        executor = SkillExecutor(registry=test_registry, event_bus=mock_event_bus, timeout=0.1)

        result = await executor.execute("long_running", {}, trace_id="trace-123")

        # It should catch the timeout and return an error string rather than hard-crashing the agent
        assert "Timeout" in result or "error" in result.lower()

        emitted = [
            call.args[0].event_type
            for call in mock_event_bus.emit.await_args_list  # type: ignore[attr-defined]
        ]
        assert EventType.TOOL_INVOKE in emitted
        assert EventType.TOOL_ERROR in emitted

    @pytest.mark.asyncio
    async def test_exception_execution(
        self, test_registry: SkillRegistry, mock_event_bus: EventBus
    ) -> None:
        """Test that a skill raising an exception is caught and emits an error event."""
        executor = SkillExecutor(registry=test_registry, event_bus=mock_event_bus)

        result = await executor.execute("broken_skill", {}, trace_id="trace-123")

        assert "I am broken" in result or "error" in result.lower()

        emitted = [
            call.args[0].event_type
            for call in mock_event_bus.emit.await_args_list  # type: ignore[attr-defined]
        ]
        assert EventType.TOOL_INVOKE in emitted
        assert EventType.TOOL_ERROR in emitted
