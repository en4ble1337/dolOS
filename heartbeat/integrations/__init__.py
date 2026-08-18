"""Heartbeat integrations package.

Provides the base class, registry, and built-in integrations that the
HeartbeatSystem can discover and run on every tick.
"""

from typing import TYPE_CHECKING

from heartbeat.integrations.base import HeartbeatIntegration, IntegrationRegistry
from heartbeat.integrations.deadman_switch import DeadManSwitch
from heartbeat.integrations.system_health import SystemHealthProbe

if TYPE_CHECKING:
    from core.telemetry import EventBus

__all__ = [
    "HeartbeatIntegration",
    "IntegrationRegistry",
    "DeadManSwitch",
    "SystemHealthProbe",
]


def create_default_registry(event_bus: "EventBus") -> IntegrationRegistry:
    """Build a registry pre-loaded with the standard integrations."""
    registry = IntegrationRegistry()
    registry.register(SystemHealthProbe(event_bus))
    registry.register(DeadManSwitch(event_bus))
    return registry
