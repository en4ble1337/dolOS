import asyncio
import inspect
from typing import Any

from core.telemetry import Event, EventBus, EventType
from skills.registry import SkillRegistry


class SkillExecutor:
    """Executes registered skills safely with timeouts and telemetry handling."""

    def __init__(
        self,
        event_bus: EventBus,
        registry: SkillRegistry | None = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Args:
            event_bus: The telemetry event bus.
            registry: The registry to lookup skills. Defaults to global if not provided.
            timeout: Maximum execution time for a skill in seconds.
        """
        from skills.registry import _default_registry
        self.registry = registry or _default_registry
        self.event_bus = event_bus
        self.timeout = timeout

    async def execute(self, name: str, kwargs: dict[str, Any], trace_id: str | None = None) -> Any:
        """
        Execute a skill by name, applying the provided arguments.
        Provides a sandbox with timeouts and telemetry emission.
        """
        try:
            func = self.registry.get_skill(name)
        except KeyError as e:
            return f"Error: {e}"

        # Emit Invoke
        await self.event_bus.emit(
            Event(
                event_type=EventType.TOOL_INVOKE,
                component="skills.executor",
                trace_id=trace_id or "pending",
                payload={"tool_name": name, "kwargs": kwargs},
            )
        )

        try:
            # We must handle both sync and async skills
            if inspect.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(**kwargs), timeout=self.timeout)
            else:
                # Wrap sync functions to run them in threadpool to prevent blocking the event loop
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, **kwargs), timeout=self.timeout
                )

            # Emit Complete
            await self.event_bus.emit(
                Event(
                    event_type=EventType.TOOL_COMPLETE,
                    component="skills.executor",
                    trace_id=trace_id or "pending",
                    payload={"tool_name": name, "result": str(result)[:500]}, # Trim massive results
                )
            )
            return result

        except asyncio.TimeoutError:
            error_msg = f"Timeout Error: Skill '{name}' exceeded {self.timeout} seconds."
            await self._emit_error(name, error_msg, trace_id)
            return error_msg

        except Exception as e:
            error_msg = f"Execution Error in skill '{name}': {e}"
            await self._emit_error(name, error_msg, trace_id)
            return error_msg

    async def _emit_error(self, name: str, error_msg: str, trace_id: str | None) -> None:
        """Helper to emit TOOL_ERROR events."""
        await self.event_bus.emit(
            Event(
                event_type=EventType.TOOL_ERROR,
                component="skills.executor",
                trace_id=trace_id or "pending",
                payload={"tool_name": name, "error": error_msg},
                success=False,
            )
        )
