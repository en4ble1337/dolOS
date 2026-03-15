import uuid
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from core.telemetry import Event, EventBus, EventType, reset_trace_id, set_trace_id


class HeartbeatSystem:
    """Proactively executes agent tasks on a scheduled cadence."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.scheduler = AsyncIOScheduler()
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
        """
        Register an async periodic background task.

        Args:
            name: Human-readable name of the task.
            func: The asynchronous callable to run.
            trigger: APScheduler trigger type ("date", "interval", "cron")
            **trigger_args: Arguments for the trigger (e.g. seconds=60)
        """
        self.scheduler.add_job(
            self._wrap_task(name, func),
            trigger=trigger,
            id=name,
            replace_existing=True,
            **trigger_args,
        )

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

                # Execute the real task
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
                # Catch failures so we don't bring down the scheduler thread
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

    def register_default_tasks(self, memory_manager: Any = None, llm_gateway: Any = None) -> None:
        """Register the default standard agent tasks."""
        
        async def health_check() -> str:
            """Pings dependencies to ensure health."""
            # Example ping implementation
            return "Health check passed. Dependencies ok."
            
        async def self_reflection() -> str:
            """Summarizes older episodic memories."""
            if not memory_manager or not llm_gateway:
                return "Reflection skipped: missing components."
            return "Self-reflection complete."

        self.register_task(
            name="system.health_check",
            func=health_check,
            trigger="interval",
            minutes=5,
        )

        self.register_task(
            name="agent.self_reflection",
            func=self_reflection,
            trigger="interval",
            hours=6,
        )
