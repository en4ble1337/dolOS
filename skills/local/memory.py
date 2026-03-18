"""Memory skill — lets the agent explicitly search its own Qdrant memory."""
from typing import Optional

from skills.registry import skill

_memory_manager = None


def set_memory_manager(memory) -> None:
    """Inject the MemoryManager instance at startup."""
    global _memory_manager
    _memory_manager = memory


@skill(
    name="search_memory",
    description=(
        "Search your own memory for relevant information. "
        "Use this to recall past conversations, facts, or context before answering. "
        "memory_type can be 'episodic' (recent conversations) or 'semantic' (long-term facts)."
    ),
)
def search_memory(query: str, memory_type: str = "episodic", limit: int = 5) -> str:
    """Search episodic or semantic memory and return matching entries."""
    if _memory_manager is None:
        return "Error: Memory manager not available."

    results = _memory_manager.search(query=query, memory_type=memory_type, limit=limit)

    if not results:
        return f"No memories found for query: '{query}'"

    lines = [f"[{memory_type} memory — {len(results)} results for '{query}']"]
    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        text = r.get("text", "").strip()
        lines.append(f"{i}. (score={score:.2f}) {text}")

    return "\n".join(lines)
