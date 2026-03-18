from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from core.telemetry import Event, EventBus, EventType, reset_trace_id, set_trace_id
from heartbeat.integrations.base import HeartbeatIntegration, IntegrationRegistry

if TYPE_CHECKING:
    from heartbeat.integrations.deadman_switch import DeadManSwitch
    from heartbeat.integrations.system_health import SystemHealthProbe

logger = logging.getLogger(__name__)


class HeartbeatSystem:
    """Proactively executes agent tasks on a scheduled cadence."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.scheduler = AsyncIOScheduler()
        self.integration_registry = IntegrationRegistry()
        self._running = False

    def start(self) -> None:
        """Start the background scheduler loop."""
        if not self._running:
            self.scheduler.start()
            self._running = True

    def shutdown(self) -> None:
        """Shut down the background scheduler loop gracefully."""
        if self._running:
            self.scheduler.shutdown()
            self._running = False

    def restart(self) -> None:
        """Shut down and restart the scheduler."""
        logger.info("HeartbeatSystem: restarting scheduler.")
        self.shutdown()
        self.start()

    def is_running(self) -> bool:
        """Check if the scheduler is active."""
        return self._running

    def register_task(
        self,
        name: str,
        func: Callable[[], Coroutine[Any, Any, Any]],
        trigger: str,
        **trigger_args: Any,
    ) -> None:
        """Register an async periodic background task."""
        self.scheduler.add_job(
            self._wrap_task(name, func),
            trigger=trigger,
            id=name,
            replace_existing=True,
            **trigger_args,
        )

    def register_integration(self, integration: HeartbeatIntegration) -> None:
        """Register an integration and schedule its check() on a 5-minute interval."""
        self.integration_registry.register(integration)
        self.register_task(
            name=f"integration.{integration.name}",
            func=integration.check,
            trigger="interval",
            minutes=5,
        )

    def register_default_tasks(
        self,
        system_health_probe: Optional["SystemHealthProbe"] = None,
        dead_man_switch: Optional["DeadManSwitch"] = None,
    ) -> None:
        """Register the default standard agent integrations."""
        if system_health_probe:
            self.register_integration(system_health_probe)
        if dead_man_switch:
            self.register_integration(dead_man_switch)

    def _wrap_task(
        self, name: str, func: Callable[[], Coroutine[Any, Any, Any]]
    ) -> Callable[[], Coroutine[Any, Any, None]]:
        """Wrap the task in a telemetry and trace boundary."""

        async def wrapped() -> None:
            trace_id = uuid.uuid4().hex
            token = set_trace_id(trace_id)

            try:
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.HEARTBEAT_START,
                        component="core.heartbeat",
                        trace_id=trace_id,
                        payload={"job_name": name},
                    )
                )

                result = await func()

                await self.event_bus.emit(
                    Event(
                        event_type=EventType.HEARTBEAT_COMPLETE,
                        component="core.heartbeat",
                        trace_id=trace_id,
                        payload={"job_name": name, "result": str(result)},
                        success=True,
                    )
                )

            except Exception as e:
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.HEARTBEAT_COMPLETE,
                        component="core.heartbeat",
                        trace_id=trace_id,
                        payload={"job_name": name, "error": str(e)},
                        success=False,
                    )
                )
            finally:
                reset_trace_id(token)

        return wrapped
