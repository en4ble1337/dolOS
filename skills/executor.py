import asyncio
import inspect
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.telemetry import Event, EventBus, EventType
from skills.local.meta import create_skill, fix_skill
from skills.registry import SkillRegistry

if TYPE_CHECKING:
    from core.llm import LLMGateway

_GENERATED_DIR = Path(__file__).parent / "local" / "generated"
_ERROR_PREFIXES = ("Timeout Error:", "Execution Error", "Error:")
_AUTO_FIX_PROMPT = """\
A generated dolOS skill failed at runtime.

Skill name: {name}
Skill description: {description}
Error: {error}
Arguments: {arguments}

Current source:
{source}

Return ONLY corrected Python code for the async function `handler`.
Rules:
- Keep the function name exactly `handler`
- Return code only, with no explanation
- The result must be a complete async function definition
"""

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Executes registered skills safely with timeouts and telemetry handling."""

    def __init__(
        self,
        event_bus: EventBus,
        registry: SkillRegistry | None = None,
        llm: "LLMGateway | None" = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Args:
            event_bus: The telemetry event bus.
            registry: The registry to lookup skills. Defaults to global if not provided.
            llm: Optional LLM used for generated skill auto-fix.
            timeout: Maximum execution time for a skill in seconds.
        """
        from skills.registry import _default_registry

        self.registry = registry or _default_registry
        self.event_bus = event_bus
        self.llm = llm
        self.timeout = timeout
        self._fix_attempted: set[str] = set()
        self._fix_attempted_trace_id: str | None = None

    async def execute(
        self,
        name: str,
        kwargs: dict[str, Any],
        trace_id: str | None = None,
    ) -> Any:
        """
        Execute a skill by name, applying the provided arguments.
        Provides a sandbox with timeouts and telemetry emission.
        """
        self._reset_fix_attempts(trace_id)
        return await self._execute(name, kwargs, trace_id, allow_auto_fix=True)

    async def _execute(
        self,
        name: str,
        kwargs: dict[str, Any],
        trace_id: str | None,
        allow_auto_fix: bool,
    ) -> Any:
        """Internal execution path with an auto-fix guard to avoid recursion loops."""
        try:
            func = self.registry.get_skill(name)
        except KeyError as e:
            return f"Error: {e}"

        await self.event_bus.emit(
            Event(
                event_type=EventType.TOOL_INVOKE,
                component="skills.executor",
                trace_id=trace_id or "pending",
                payload={"tool_name": name, "kwargs": kwargs},
            )
        )

        try:
            if inspect.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(**kwargs), timeout=self.timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, **kwargs), timeout=self.timeout
                )

            await self.event_bus.emit(
                Event(
                    event_type=EventType.TOOL_COMPLETE,
                    component="skills.executor",
                    trace_id=trace_id or "pending",
                    payload={"tool_name": name, "result": str(result)[:500]},
                )
            )
            return result

        except asyncio.TimeoutError:
            error_msg = f"Timeout Error: Skill '{name}' exceeded {self.timeout} seconds."
            return await self._handle_execution_failure(
                name=name,
                kwargs=kwargs,
                trace_id=trace_id,
                error_msg=error_msg,
                allow_auto_fix=allow_auto_fix,
            )

        except Exception as e:
            error_msg = f"Execution Error in skill '{name}': {e}"
            return await self._handle_execution_failure(
                name=name,
                kwargs=kwargs,
                trace_id=trace_id,
                error_msg=error_msg,
                allow_auto_fix=allow_auto_fix,
            )

    def _reset_fix_attempts(self, trace_id: str | None) -> None:
        """Clear per-trace fix attempts when a new top-level execution starts."""
        if trace_id is None:
            self._fix_attempted.clear()
            self._fix_attempted_trace_id = None
            return
        if self._fix_attempted_trace_id != trace_id:
            self._fix_attempted.clear()
            self._fix_attempted_trace_id = trace_id

    async def _handle_execution_failure(
        self,
        name: str,
        kwargs: dict[str, Any],
        trace_id: str | None,
        error_msg: str,
        allow_auto_fix: bool,
    ) -> Any:
        """Attempt auto-fix for generated skills, otherwise fall back to the original error."""
        if allow_auto_fix:
            auto_fix_result = await self._attempt_auto_fix(
                name=name,
                error=error_msg,
                kwargs=kwargs,
                trace_id=trace_id,
            )
            if auto_fix_result is not None:
                return auto_fix_result

        if self._is_generated_skill(name):
            error_msg += self._generated_skill_hint(name)
        await self._emit_error(name, error_msg, trace_id)
        return error_msg

    async def _attempt_auto_fix(
        self,
        name: str,
        error: str,
        kwargs: dict[str, Any],
        trace_id: str | None,
    ) -> Any | None:
        """For generated skills only: read source, ask the LLM to fix it, and rewrite it."""
        if self.llm is None or not self._is_generated_skill(name) or name in self._fix_attempted:
            return None

        try:
            registration = self.registry.get_registration(name)
        except KeyError:
            return None

        self._fix_attempted.add(name)
        current_trace = trace_id or "pending"
        await self.event_bus.emit(
            Event(
                event_type=EventType.SKILL_AUTO_FIX_ATTEMPT,
                component="skills.executor",
                trace_id=current_trace,
                payload={"tool_name": name, "error": error},
            )
        )

        try:
            source = await fix_skill(name)
            if source.startswith("Error:"):
                raise RuntimeError(source)

            prompt = _AUTO_FIX_PROMPT.format(
                name=name,
                description=registration.description,
                error=error,
                arguments=json.dumps(kwargs, sort_keys=True),
                source=source,
            )
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                trace_id=current_trace,
            )
            fixed_code = _extract_handler_code(getattr(response, "content", "") or "")
            if fixed_code is None:
                raise ValueError("LLM did not return a valid async handler")

            create_result = await create_skill(
                name=name,
                description=registration.description,
                code=fixed_code,
                is_read_only=registration.is_read_only,
                concurrency_safe=registration.concurrency_safe,
            )
            if isinstance(create_result, str) and create_result.startswith("Error:"):
                raise RuntimeError(create_result)

            if registration.is_read_only:
                retry_result = await self._execute(
                    name=name,
                    kwargs=kwargs,
                    trace_id=trace_id,
                    allow_auto_fix=False,
                )
                if self._looks_like_error_result(retry_result):
                    raise RuntimeError(str(retry_result))
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.SKILL_AUTO_FIX_SUCCESS,
                        component="skills.executor",
                        trace_id=current_trace,
                        payload={"tool_name": name, "reexecuted": True},
                    )
                )
                return retry_result

            note = (
                f"Skill '{name}' was auto-fixed but not re-executed because it is not read-only. "
                "Re-invoke it to run the corrected version."
            )
            await self.event_bus.emit(
                Event(
                    event_type=EventType.SKILL_AUTO_FIX_SUCCESS,
                    component="skills.executor",
                    trace_id=current_trace,
                    payload={"tool_name": name, "reexecuted": False},
                )
            )
            return note

        except Exception as exc:
            logger.warning("Auto-fix failed for generated skill '%s': %s", name, exc)
            await self.event_bus.emit(
                Event(
                    event_type=EventType.SKILL_AUTO_FIX_FAILED,
                    component="skills.executor",
                    trace_id=current_trace,
                    payload={"tool_name": name, "error": str(exc)},
                    success=False,
                )
            )
            return None

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

    def _is_generated_skill(self, name: str) -> bool:
        """Return True when the skill corresponds to a file in generated/."""
        return (_GENERATED_DIR / f"{name}.py").exists()

    def _generated_skill_hint(self, name: str) -> str:
        """Return the fallback user-facing hint for broken generated skills."""
        return (
            f" â€” This is a generated skill. "
            f"Call fix_skill(name='{name}') to retrieve its current source, "
            f"then call create_skill(name='{name}', ...) with corrected code to replace it."
        )

    def _looks_like_error_result(self, result: Any) -> bool:
        """Heuristic to detect when a retried skill still returned an execution error."""
        return isinstance(result, str) and result.startswith(_ERROR_PREFIXES)


def _extract_handler_code(content: str) -> str | None:
    """Extract `async def handler(...)` code from plain text or fenced code."""
    text = content.strip()
    text = re.sub(r"^```(?:python)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"async\s+def\s+handler\b[\s\S]*", text)
    if match is None:
        return None
    return match.group(0).strip()
