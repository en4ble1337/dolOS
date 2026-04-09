"""spawn_subagent skill — creates a scoped sub-agent to run a task (Gap 6).

This skill lets the parent agent delegate a focused task to a child agent
that is restricted to a specific set of tools.  The sub-agent runs
synchronously (awaited inline) and returns its response as a string.

Isolation mechanism
-------------------
``spawn_subagent(task, tools)`` constructs a new :class:`~core.agent.Agent`
with ``PermissionPolicy(allow_only=set(tools))``.  This means the sub-agent's
LLM only sees schemas for the listed tools — it *cannot* call any other skill,
even if the parent agent can.

Dependency injection
--------------------
The skill requires references to the shared LLM, memory, and skill executor.
These must be set via :func:`set_subagent_dependencies` at startup (see
``main.py``).  This mirrors the pattern used by ``skills/local/session_memory.py``.

Emits ``[SUBAGENT]`` INFO log entries at spawn and completion.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from skills.registry import _default_registry as _registry, skill

logger = logging.getLogger(__name__)

# Module-level references populated by set_subagent_dependencies()
_llm: Any = None
_memory: Any = None
_skill_executor: Any = None


def set_subagent_dependencies(llm: Any, memory: Any, skill_executor: Any) -> None:
    """Wire in the shared LLM, memory, and skill executor for subagent use.

    Call this once at startup before any call to ``spawn_subagent``.

    Args:
        llm:            Shared :class:`~core.llm.LLMGateway` instance.
        memory:         Shared :class:`~memory.memory_manager.MemoryManager` instance.
        skill_executor: Shared :class:`~skills.executor.SkillExecutor` instance.
    """
    global _llm, _memory, _skill_executor
    _llm = llm
    _memory = memory
    _skill_executor = skill_executor


@skill(
    name="spawn_subagent",
    description=(
        "Spawn a scoped sub-agent to execute a focused task with a restricted set of tools. "
        "The sub-agent can only call the skills listed in 'tools'. "
        "Returns the sub-agent's response as a string."
    ),
    read_only=False,
    concurrency_safe=False,
)
async def spawn_subagent(task: str, tools: list) -> str:
    """Spawn a scoped sub-agent with limited tool access.

    Args:
        task:  Natural-language task description for the sub-agent.
        tools: List of skill names the sub-agent is allowed to call.
               Pass an empty list to give the sub-agent no tools.

    Returns:
        The sub-agent's final response string, or an error message if
        dependencies are not configured or the sub-agent fails.
    """
    if _llm is None or _memory is None or _skill_executor is None:
        return (
            "Error: subagent dependencies not configured. "
            "Call set_subagent_dependencies() before using spawn_subagent."
        )

    allow_only: set[str] = set(tools) if tools else set()
    sub_session = f"subagent-{uuid.uuid4().hex[:8]}"

    logger.info(
        "[SUBAGENT] Spawning | session=%s | task=%r | allow_only=%s",
        sub_session,
        task[:80],
        sorted(allow_only),
    )

    from core.agent import Agent
    from skills.permissions import PermissionPolicy

    policy = PermissionPolicy(allow_only=allow_only if allow_only is not None else None)

    sub_agent = Agent(
        llm=_llm,
        memory=_memory,
        skill_executor=_skill_executor,
        permission_policy=policy,
    )

    try:
        result = await sub_agent.process_message(sub_session, task)
    except Exception as exc:
        logger.exception("[SUBAGENT] Failed | session=%s | error=%s", sub_session, exc)
        return f"Error: subagent '{sub_session}' failed: {exc}"

    logger.info(
        "[SUBAGENT] Completed | session=%s | result_len=%d",
        sub_session,
        len(result),
    )
    return result
