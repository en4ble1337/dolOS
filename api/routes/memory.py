"""Memory routes for searching and inspecting agent memory."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["memory"])


class MemorySearchResult(BaseModel):
    """Single memory search result."""
    text: str
    score: float
    timestamp: float
    importance: float
    similarity: float
    metadata: dict[str, Any]


class MemorySearchResponse(BaseModel):
    """Response for memory search queries."""
    query: str
    results: list[MemorySearchResult]
    count: int


class MemoryStatsResponse(BaseModel):
    """Memory collection statistics."""
    collections: dict[str, Any]


def _get_memory(request: Request):
    memory = getattr(request.app.state, "memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="MemoryManager not configured")
    return memory


@router.get("/memory/search", response_model=MemorySearchResponse)
async def search_memory(
    request: Request,
    q: str,
    memory_type: str = "episodic",
    limit: int = 5,
) -> MemorySearchResponse:
    """Search agent memories by query string."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' must not be empty")

    memory = _get_memory(request)

    try:
        results = memory.search(query=q, memory_type=memory_type, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory search failed: {e}")

    return MemorySearchResponse(
        query=q,
        results=[
            MemorySearchResult(
                text=r["text"],
                score=r["score"],
                timestamp=r["timestamp"],
                importance=r["importance"],
                similarity=r["similarity"],
                metadata=r.get("metadata", {}),
            )
            for r in results
        ],
        count=len(results),
    )


@router.get("/memory/stats", response_model=MemoryStatsResponse)
async def memory_stats(request: Request) -> MemoryStatsResponse:
    """Return memory collection statistics."""
    memory = _get_memory(request)

    stats: dict[str, Any] = {}
    try:
        for collection_name in ["episodic", "semantic"]:
            info = memory.vector_store.client.get_collection(collection_name)
            stats[collection_name] = {
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": str(info.status),
            }
    except Exception as e:
        stats["error"] = str(e)

    return MemoryStatsResponse(collections=stats)
