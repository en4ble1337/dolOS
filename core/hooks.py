"""Hook framework for dolOS (Gap 12).

Provides ``HookRegistry`` — a lightweight event system supporting both blocking
hooks (which can veto an action by raising ``HookVeto``) and fire-and-forget
hooks (which run as background asyncio tasks).

Supported events
----------------
* ``pre_tool_use``       — fired before each tool call; blocking hooks may veto.
* ``permission_request`` — fired when a permission check occurs.

Usage
-----
    from core.hooks import HookRegistry, HookVeto

    hooks = HookRegistry()

    async def audit_log(**kwargs):
        print(f"[AUDIT] {kwargs}")

    async def block_delete(**kwargs):
        if kwargs.get("tool_name", "").startswith("delete"):
            raise HookVeto("delete operations are not allowed")

    hooks.register("pre_tool_use", audit_log, blocking=False)
    hooks.register("pre_tool_use", block_delete, blocking=True)

    await hooks.fire("pre_tool_use", tool_name="delete_file")  # raises HookVeto
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class HookVeto(Exception):
    """Raised by a blocking hook to veto (cancel) the associated action.

    Any blocking hook may raise this to prevent the action from proceeding.
    The exception propagates to the caller of ``HookRegistry.fire()``.
    """


class HookRegistry:
    """Registry of event hooks with blocking and fire-and-forget semantics.

    Blocking hooks (``blocking=True``) are awaited in registration order
    before ``fire()`` returns.  Any exception (including ``HookVeto``) propagates.

    Fire-and-forget hooks (``blocking=False``) are scheduled as background
    asyncio tasks via ``asyncio.create_task()``.  Exceptions in these hooks
    are logged but do not propagate to the caller.
    """

    def __init__(self) -> None:
        # Each entry is a tuple of (coroutine_function, is_blocking)
        self._hooks: dict[str, list[tuple[Callable[..., Coroutine[Any, Any, Any]], bool]]] = (
            defaultdict(list)
        )

    def register(
        self,
        event: str,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        blocking: bool = False,
    ) -> None:
        """Register *fn* to be called when *event* fires.

        Args:
            event:    Event name (e.g. ``"pre_tool_use"``).
            fn:       Async callable accepting ``**kwargs``.
            blocking: If ``True``, the hook is awaited and may raise ``HookVeto``.
                      If ``False``, it runs as a background task (fire-and-forget).
        """
        self._hooks[event].append((fn, blocking))

    async def fire(self, event: str, **kwargs: Any) -> None:
        """Fire all hooks registered for *event*.

        Blocking hooks are awaited in order; any exception propagates immediately
        (stopping remaining blocking hooks).  Non-blocking hooks are scheduled
        as background tasks and do not block the caller.

        Args:
            event:   Event name.
            **kwargs: Arbitrary context passed to every hook as keyword arguments.

        Raises:
            HookVeto: Re-raised from any blocking hook that raises it.
            Exception: Any other exception from a blocking hook also propagates.
        """
        for fn, is_blocking in self._hooks.get(event, []):
            if is_blocking:
                await fn(**kwargs)
            else:
                async def _run(hook: Callable[..., Coroutine[Any, Any, Any]], kw: dict[str, Any]) -> None:
                    try:
                        await hook(**kw)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[HOOK] Fire-and-forget hook %r raised: %s", hook, exc)

                asyncio.create_task(_run(fn, kwargs))
