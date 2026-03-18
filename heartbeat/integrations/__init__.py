"""Heartbeat integrations package.

Provides the base class, registry, and built-in integrations that the
HeartbeatSystem can discover and run on every tick.
"""

from heartbeat.integrations.base import HeartbeatIntegration, IntegrationRegistry
from heartbeat.integrations.deadman_switch import DeadManSwitch
from heartbeat.integrations.system_health import SystemHealthProbe

__all__ = [
    "HeartbeatIntegration",
    "IntegrationRegistry",
    "DeadManSwitch",
    "SystemHealthProbe",
]


def create_default_registry(event_bus: "EventBus") -> IntegrationRegistry:  # noqa: F821
    """Build a registry pre-loaded with the standard integrations."""
    from core.telemetry import EventBus as _EventBus  # avoid circular at module level

    registry = IntegrationRegistry()
    registry.register(SystemHealthProbe(event_bus))
    registry.register(DeadManSwitch(event_bus))
    return registry
