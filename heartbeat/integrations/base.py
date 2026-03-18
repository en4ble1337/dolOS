"""Abstract base class and registry for heartbeat integrations.

Every heartbeat integration implements the ``HeartbeatIntegration`` ABC and
registers itself via the ``IntegrationRegistry``.  The heartbeat loop discovers
all registered integrations at startup and calls ``check()`` on each one during
every tick.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from core.reliability import retry_with_backoff
from core.telemetry import Event, EventBus, EventType

logger = logging.getLogger(__name__)


class HeartbeatIntegration(ABC):
    """Base class that all heartbeat integrations must implement.

    Subclasses must override ``check()`` which returns a dict containing
    the integration's status payload.  The base class provides a
    ``run()`` wrapper that handles telemetry emission, timing, and
    retry logic automatically.
    """

    #: Human-readable name used in telemetry events and logging.
    name: str = "unnamed_integration"

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    @abstractmethod
    async def check(self) -> dict[str, Any]:
        """Execute the integration's health/status check.

        Returns:
            A dict payload describing the result (keys are integration-specific).
        """
        ...

    @retry_with_backoff(max_attempts=2, base_delay=0.5, max_delay=5.0)
    async def run(self, trace_id: str) -> dict[str, Any]:
        """Execute ``check()`` wrapped in telemetry and retry logic.

        This is the method the heartbeat loop should call.  It emits
        ``HEARTBEAT_START`` / ``HEARTBEAT_COMPLETE`` events and measures
        wall-clock duration.
        """
        start = time.time()
        await self.event_bus.emit(
            Event(
                event_type=EventType.HEARTBEAT_START,
                component=f"heartbeat.integration.{self.name}",
                trace_id=trace_id,
                payload={"integration": self.name},
            )
        )

        try:
            result = await self.check()
            duration_ms = (time.time() - start) * 1000

            await self.event_bus.emit(
                Event(
                    event_type=EventType.HEARTBEAT_COMPLETE,
                    component=f"heartbeat.integration.{self.name}",
                    trace_id=trace_id,
                    payload={"integration": self.name, "result": result},
                    duration_ms=duration_ms,
                    success=True,
                )
            )
            return result

        except Exception as exc:
            duration_ms = (time.time() - start) * 1000

            await self.event_bus.emit(
                Event(
                    event_type=EventType.HEARTBEAT_COMPLETE,
                    component=f"heartbeat.integration.{self.name}",
                    trace_id=trace_id,
                    payload={"integration": self.name, "error": str(exc)},
                    duration_ms=duration_ms,
                    success=False,
                )
            )
            raise


class IntegrationRegistry:
    """Central registry that the heartbeat loop queries for integrations.

    Usage::

        registry = IntegrationRegistry()
        registry.register(SystemHealthProbe(event_bus))
        registry.register(DeadManSwitch(event_bus))

        # In the heartbeat loop:
        for integration in registry.all():
            await integration.run(trace_id)
    """

    def __init__(self) -> None:
        self._integrations: dict[str, HeartbeatIntegration] = {}

    def register(self, integration: HeartbeatIntegration) -> None:
        """Register an integration instance.  Replaces any existing entry with the same name."""
        self._integrations[integration.name] = integration
        logger.info("Registered heartbeat integration: %s", integration.name)

    def unregister(self, name: str) -> None:
        """Remove a previously registered integration by name."""
        removed = self._integrations.pop(name, None)
        if removed is not None:
            logger.info("Unregistered heartbeat integration: %s", name)

    def get(self, name: str) -> HeartbeatIntegration | None:
        """Look up a single integration by name."""
        return self._integrations.get(name)

    def all(self) -> list[HeartbeatIntegration]:
        """Return all registered integrations in insertion order."""
        return list(self._integrations.values())

    def names(self) -> list[str]:
        """Return the names of all registered integrations."""
        return list(self._integrations.keys())

    def clear(self) -> None:
        """Remove all registered integrations."""
        self._integrations.clear()
