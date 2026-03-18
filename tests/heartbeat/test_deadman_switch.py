"""Tests for DeadManSwitch restart and escalation logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.telemetry import EventBus, EventType
from heartbeat.integrations.deadman_switch import DeadManSwitch


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return bus


def _make_switch(
    mock_event_bus: EventBus,
    max_silence: float = 10.0,
    max_restart_attempts: int = 3,
    on_restart=None,
    alert_notifier=None,
) -> DeadManSwitch:
    return DeadManSwitch(
        event_bus=mock_event_bus,
        max_silence=max_silence,
        max_restart_attempts=max_restart_attempts,
        on_restart=on_restart,
        alert_notifier=alert_notifier,
    )


class TestDeadManSwitchRestartEscalation:
    @pytest.mark.asyncio
    async def test_healthy_tick_resets_state(self, mock_event_bus: EventBus) -> None:
        switch = _make_switch(mock_event_bus, max_silence=9999)
        result = await switch.check()
        assert result["status"] == "healthy"
        assert switch.restart_attempts == 0
        assert switch._escalated is False

    @pytest.mark.asyncio
    async def test_fired_triggers_restart_callback(self, mock_event_bus: EventBus) -> None:
        on_restart = MagicMock()
        switch = _make_switch(mock_event_bus, max_silence=0.0, on_restart=on_restart)
        result = await switch.check()
        on_restart.assert_called_once()
        assert switch.restart_attempts == 1
        assert result["status"] == "restarting"

    @pytest.mark.asyncio
    async def test_restart_counter_increments_on_each_fire(self, mock_event_bus: EventBus) -> None:
        on_restart = MagicMock()
        switch = _make_switch(mock_event_bus, max_silence=0.0, on_restart=on_restart, max_restart_attempts=3)
        await switch.check()
        await switch.check()
        await switch.check()
        assert switch.restart_attempts == 3

    @pytest.mark.asyncio
    async def test_escalates_after_max_attempts(self, mock_event_bus: EventBus) -> None:
        on_restart = MagicMock()
        mock_notifier = AsyncMock()
        switch = _make_switch(
            mock_event_bus, max_silence=0.0, max_restart_attempts=2,
            on_restart=on_restart, alert_notifier=mock_notifier,
        )
        await switch.check()  # attempt 1
        await switch.check()  # attempt 2
        await switch.check()  # exceeds max → escalate
        mock_notifier.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_escalate_fires_only_once(self, mock_event_bus: EventBus) -> None:
        on_restart = MagicMock()
        mock_notifier = AsyncMock()
        switch = _make_switch(
            mock_event_bus, max_silence=0.0, max_restart_attempts=1,
            on_restart=on_restart, alert_notifier=mock_notifier,
        )
        await switch.check()  # attempt 1
        await switch.check()  # escalate
        await switch.check()  # already escalated — no second alert
        await switch.check()
        mock_notifier.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_resets_escalation(self, mock_event_bus: EventBus) -> None:
        switch = _make_switch(mock_event_bus, max_silence=0.0, max_restart_attempts=1)
        await switch.check()  # attempt 1
        await switch.check()  # escalate — _escalated = True
        # Now simulate recovery: large max_silence so elapsed < threshold
        switch.max_silence = 9999.0
        result = await switch.check()
        assert result["status"] == "healthy"
        assert switch.restart_attempts == 0
        assert switch._escalated is False

    @pytest.mark.asyncio
    async def test_no_escalation_without_notifier(self, mock_event_bus: EventBus) -> None:
        switch = _make_switch(mock_event_bus, max_silence=0.0, max_restart_attempts=1)
        await switch.check()  # attempt 1
        # Should not raise even without notifier
        await switch.check()

    @pytest.mark.asyncio
    async def test_no_restart_without_callback(self, mock_event_bus: EventBus) -> None:
        switch = _make_switch(mock_event_bus, max_silence=0.0)
        result = await switch.check()
        # No crash; attempts still increments
        assert switch.restart_attempts == 1

    @pytest.mark.asyncio
    async def test_restart_callback_failure_is_swallowed(self, mock_event_bus: EventBus) -> None:
        on_restart = MagicMock(side_effect=RuntimeError("crash"))
        switch = _make_switch(mock_event_bus, max_silence=0.0, on_restart=on_restart)
        # Must not raise
        await switch.check()

    @pytest.mark.asyncio
    async def test_result_dict_keys_healthy(self, mock_event_bus: EventBus) -> None:
        switch = _make_switch(mock_event_bus, max_silence=9999)
        result = await switch.check()
        for key in ("elapsed_seconds", "max_silence_seconds", "fired", "restart_attempts", "status"):
            assert key in result

    @pytest.mark.asyncio
    async def test_result_dict_keys_fired(self, mock_event_bus: EventBus) -> None:
        switch = _make_switch(mock_event_bus, max_silence=0.0)
        result = await switch.check()
        for key in ("elapsed_seconds", "max_silence_seconds", "fired", "restart_attempts", "status"):
            assert key in result

    def test_public_properties(self, mock_event_bus: EventBus) -> None:
        switch = _make_switch(mock_event_bus)
        assert isinstance(switch.last_ping_elapsed, float)
        assert switch.restart_attempts == 0
