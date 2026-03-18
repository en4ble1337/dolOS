"""Tests for heartbeat integrations: base, system_health, deadman_switch."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.telemetry import EventBus, EventType
from heartbeat.integrations.base import HeartbeatIntegration, IntegrationRegistry
from heartbeat.integrations.deadman_switch import DeadManSwitch
from heartbeat.integrations.system_health import SystemHealthProbe


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


# --- IntegrationRegistry ---


class TestIntegrationRegistry:
    def test_register_and_list(self, mock_event_bus: EventBus) -> None:
        registry = IntegrationRegistry()
        probe = SystemHealthProbe(mock_event_bus)
        registry.register(probe)

        assert "system_health" in registry.names()
        assert registry.get("system_health") is probe
        assert len(registry.all()) == 1

    def test_unregister(self, mock_event_bus: EventBus) -> None:
        registry = IntegrationRegistry()
        registry.register(SystemHealthProbe(mock_event_bus))
        registry.unregister("system_health")

        assert registry.get("system_health") is None
        assert len(registry.all()) == 0

    def test_clear(self, mock_event_bus: EventBus) -> None:
        registry = IntegrationRegistry()
        registry.register(SystemHealthProbe(mock_event_bus))
        registry.register(DeadManSwitch(mock_event_bus))
        assert len(registry.all()) == 2

        registry.clear()
        assert len(registry.all()) == 0

    def test_register_replaces_existing(self, mock_event_bus: EventBus) -> None:
        registry = IntegrationRegistry()
        probe1 = SystemHealthProbe(mock_event_bus)
        probe2 = SystemHealthProbe(mock_event_bus)
        registry.register(probe1)
        registry.register(probe2)

        assert registry.get("system_health") is probe2
        assert len(registry.all()) == 1


# --- SystemHealthProbe ---


class TestSystemHealthProbe:
    @pytest.mark.asyncio
    async def test_check_returns_disk_info(self, mock_event_bus: EventBus) -> None:
        probe = SystemHealthProbe(mock_event_bus, disk_path=".")
        result = await probe.check()

        assert "disk" in result
        assert "used_pct" in result["disk"]
        assert "total_bytes" in result["disk"]
        assert result["status"] in ("healthy", "warning")

    @pytest.mark.asyncio
    async def test_run_emits_telemetry(self, mock_event_bus: EventBus) -> None:
        probe = SystemHealthProbe(mock_event_bus, disk_path=".")
        await probe.run(trace_id="test-trace-123")

        emitted_types = [
            call.args[0].event_type
            for call in mock_event_bus.emit.await_args_list
        ]
        assert EventType.HEARTBEAT_START in emitted_types
        assert EventType.HEARTBEAT_COMPLETE in emitted_types

    @pytest.mark.asyncio
    async def test_warning_on_low_threshold(self, mock_event_bus: EventBus) -> None:
        # Set threshold to 0% so it always triggers
        probe = SystemHealthProbe(mock_event_bus, disk_path=".", disk_warn_pct=0.0)
        result = await probe.check()

        assert result["status"] == "warning"
        assert len(result["warnings"]) > 0


# --- DeadManSwitch ---


class TestDeadManSwitch:
    @pytest.mark.asyncio
    async def test_healthy_when_recent(self, mock_event_bus: EventBus) -> None:
        switch = DeadManSwitch(mock_event_bus, max_silence=60.0)
        result = await switch.check()

        assert result["status"] == "healthy"
        assert result["fired"] is False

    @pytest.mark.asyncio
    async def test_fires_when_stale(self, mock_event_bus: EventBus) -> None:
        switch = DeadManSwitch(mock_event_bus, max_silence=0.0)
        # Force the last ping to be in the past
        switch._last_ping = time.time() - 100

        result = await switch.check()

        # Switch fires → first attempt is a restart attempt
        assert result["status"] in ("restarting", "escalated")
        assert result["fired"] is True

        # Should have emitted a HEARTBEAT_MISS event
        emitted_types = [
            call.args[0].event_type
            for call in mock_event_bus.emit.await_args_list
        ]
        assert EventType.HEARTBEAT_MISS in emitted_types

    @pytest.mark.asyncio
    async def test_resets_after_check(self, mock_event_bus: EventBus) -> None:
        switch = DeadManSwitch(mock_event_bus, max_silence=1000.0)
        await switch.check()

        # Second check should still be healthy since we just pinged
        result = await switch.check()
        assert result["status"] == "healthy"


# --- create_default_registry ---


class TestCreateDefaultRegistry:
    def test_creates_with_defaults(self, mock_event_bus: EventBus) -> None:
        from heartbeat.integrations import create_default_registry

        registry = create_default_registry(mock_event_bus)

        assert "system_health" in registry.names()
        assert "deadman_switch" in registry.names()
        assert len(registry.all()) == 2
