"""Memory skill - lets the agent search memory and transcripts."""

from typing import Any

from skills.registry import skill

_memory_manager: Any = None
_transcript_index: Any = None


def set_memory_manager(memory: Any) -> None:
    """Inject the MemoryManager instance at startup."""
    global _memory_manager
    _memory_manager = memory


def set_transcript_index(index: Any | None) -> None:
    """Inject the TranscriptIndex instance at startup."""
    global _transcript_index
    _transcript_index = index


@skill(
    name="search_memory",
    description=(
        "Search your own memory for relevant information. "
        "Use this to recall past conversations, facts, or context before answering. "
        "memory_type can be 'episodic' (recent conversations) or 'semantic' (long-term facts)."
    ),
    read_only=True,
    concurrency_safe=True,
)
def search_memory(query: str, memory_type: str = "episodic", limit: int = 5) -> str:
    """Search episodic or semantic memory and return matching entries."""
    if _memory_manager is None:
        return "Error: Memory manager not available."

    results = _memory_manager.search(query=query, memory_type=memory_type, limit=limit)

    if not results:
        return f"No memories found for query: '{query}'"

    lines = [f"[{memory_type} memory - {len(results)} results for '{query}']"]
    for i, result in enumerate(results, 1):
        score = result.get("score", 0)
        text = result.get("text", "").strip()
        lines.append(f"{i}. (score={score:.2f}) {text}")

    return "\n".join(lines)


@skill(
    name="search_transcripts",
    description=(
        "Full-text search across all past conversation transcripts. "
        "Use when you need to recall exactly what was said in a previous session. "
        "Complements search_memory (which uses vector similarity)."
    ),
    read_only=True,
    concurrency_safe=True,
)
def search_transcripts(query: str, limit: int = 10) -> str:
    """Search transcript history using the configured SQLite FTS index."""
    if _transcript_index is None:
        return "Error: Transcript index not available."

    results = _transcript_index.search(query=query, limit=limit)
    if not results:
        return f"No transcripts found for query: '{query}'"

    lines = [f"[transcript search - {len(results)} results for '{query}']"]
    for i, result in enumerate(results, 1):
        session_id = result.get("session_id", "unknown-session")
        entry_type = result.get("entry_type", "unknown")
        timestamp = result.get("timestamp", "unknown-time")
        content = _preview_text(str(result.get("content", "")))
        lines.append(f"{i}. [{session_id}] {entry_type} @ {timestamp} - {content}")

    return "\n".join(lines)


def _preview_text(text: str, max_length: int = 160) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3].rstrip() + "..."
