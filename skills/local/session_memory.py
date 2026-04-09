"""Session memory skills — allow the agent to read/write its own session K/V store.

These skills give the LLM a lightweight, exact-recall mechanism for structured
per-session facts that are too specific for vector memory:
- user preferences ("preferred_language", "output_format")
- active task context ("current_branch", "working_directory")
- temporary working notes

The K/V pairs are persisted to disk so they survive short process restarts.
They will be injected into the system prompt by PromptBuilder (Phase 2).
"""

from __future__ import annotations

from memory.session_kv import get_default_store
from skills.registry import skill


@skill(
    name="set_session_memory",
    description=(
        "Store a key-value pair in your session memory for exact recall later. "
        "Use this to remember user preferences, active task context, or any "
        "structured fact that you want to retrieve precisely (not by semantic search). "
        "Values are plain strings. Keys should be short snake_case identifiers."
    ),
    read_only=False,
    concurrency_safe=False,
)
async def set_session_memory(session_id: str, key: str, value: str) -> str:
    """Set a key-value pair in the session K/V store.

    Args:
        session_id: The current session identifier.
        key: Short snake_case key (e.g. 'preferred_language').
        value: String value to store.

    Returns:
        Confirmation message.
    """
    get_default_store().set(session_id, key, value)
    return f"Session memory updated: {key} = {value!r}"


@skill(
    name="get_session_memory",
    description=(
        "Retrieve a value you previously stored in your session memory by its exact key. "
        "Returns the value as a string, or an empty string if the key does not exist."
    ),
    read_only=True,
    concurrency_safe=True,
)
async def get_session_memory(session_id: str, key: str) -> str:
    """Get a value from the session K/V store by key.

    Args:
        session_id: The current session identifier.
        key: The key to look up.

    Returns:
        The stored value, or an empty string if not found.
    """
    value = get_default_store().get(session_id, key)
    if value is None:
        return f"No session memory entry found for key: {key!r}"
    return value


@skill(
    name="list_session_memory",
    description=(
        "List all key-value pairs currently stored in your session memory. "
        "Useful for reviewing what you have already saved before adding new entries."
    ),
    read_only=True,
    concurrency_safe=True,
)
async def list_session_memory(session_id: str) -> str:
    """List all key-value pairs in the session store.

    Args:
        session_id: The current session identifier.

    Returns:
        A formatted string of all stored key-value pairs, or a notice if empty.
    """
    store = get_default_store().get_all(session_id)
    if not store:
        return "Session memory is empty."
    lines = [f"  {k}: {v}" for k, v in sorted(store.items())]
    return "Session memory:\n" + "\n".join(lines)
