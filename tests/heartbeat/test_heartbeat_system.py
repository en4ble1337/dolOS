"""Tests for HeartbeatSystem integration wiring."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.heartbeat import HeartbeatSystem
from core.telemetry import EventBus
from heartbeat.integrations.deadman_switch import DeadManSwitch
from heartbeat.integrations.system_health import SystemHealthProbe


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def heartbeat(mock_event_bus: EventBus) -> HeartbeatSystem:
    return HeartbeatSystem(event_bus=mock_event_bus)


class TestHeartbeatSystemWiring:
    def test_register_integration_schedules_job(
        self, heartbeat: HeartbeatSystem, mock_event_bus: EventBus
    ) -> None:
        probe = SystemHealthProbe(mock_event_bus)
        heartbeat.register_integration(probe)

        job_ids = [j.id for j in heartbeat.scheduler.get_jobs()]
        assert "integration.system_health" in job_ids

    def test_register_default_tasks_wires_both_integrations(
        self, heartbeat: HeartbeatSystem, mock_event_bus: EventBus
    ) -> None:
        probe = SystemHealthProbe(mock_event_bus)
        switch = DeadManSwitch(mock_event_bus)
        heartbeat.register_default_tasks(system_health_probe=probe, dead_man_switch=switch)

        job_ids = [j.id for j in heartbeat.scheduler.get_jobs()]
        assert "integration.system_health" in job_ids
        assert "integration.deadman_switch" in job_ids

    def test_old_stubs_removed(
        self, heartbeat: HeartbeatSystem, mock_event_bus: EventBus
    ) -> None:
        probe = SystemHealthProbe(mock_event_bus)
        switch = DeadManSwitch(mock_event_bus)
        heartbeat.register_default_tasks(system_health_probe=probe, dead_man_switch=switch)

        job_ids = [j.id for j in heartbeat.scheduler.get_jobs()]
        assert "system.health_check" not in job_ids
        assert "agent.self_reflection" not in job_ids

    def test_old_params_not_accepted(self, heartbeat: HeartbeatSystem) -> None:
        params = inspect.signature(heartbeat.register_default_tasks).parameters
        assert "memory_manager" not in params
        assert "llm_gateway" not in params

    def test_restart_method_exists(self, heartbeat: HeartbeatSystem) -> None:
        assert callable(getattr(heartbeat, "restart", None))
