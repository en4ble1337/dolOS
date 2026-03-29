import math
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, cast

from core.telemetry import Event, EventBus, EventType
from memory.search import EmbeddingService
from memory.vector_store import VectorStore


class MemoryManager:
    """Orchestrator for agent memory, handling episodic and semantic storage."""

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        embedding_service: Optional[EmbeddingService] = None,
        event_bus: Optional[EventBus] = None,
        recency_decay_days: int = 90
    ) -> None:
        """Initialize memory collections and services.

        Args:
            vector_store: Optional VectorStore instance.
            embedding_service: Optional EmbeddingService instance.
            event_bus: Optional EventBus for telemetry.
            recency_decay_days: Half-life for exponential recency decay in days.
        """
        self.vector_store = vector_store or VectorStore()
        self.embedding_service = embedding_service or EmbeddingService()
        self.event_bus = event_bus
        self.recency_decay_days = recency_decay_days

        # Ensure collections exist
        dim = self.embedding_service.dimension
        self.vector_store.create_collection("episodic", dim)
        self.vector_store.create_collection("semantic", dim)

    def add_memory(
        self,
        text: str,
        memory_type: Literal["episodic", "semantic"] = "episodic",
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Embed and store a memory.

        Args:
            text: Content of the memory.
            memory_type: Which collection to use.
            importance: User or agent assigned importance (0.0 to 1.0).
            metadata: Additional context.
        """
        vector_result = self.embedding_service.encode(text)

        # Type narrowing for mypy
        if isinstance(vector_result, list) and len(vector_result) > 0 and isinstance(vector_result[0], list):
            # This is a list of lists, but we expect a single vector
            vector = cast(List[float], vector_result[0])
        else:
            vector = cast(List[float], vector_result)

        payload = {
            "text": text,
            "timestamp": time.time(),
            "importance": importance,
            **(metadata or {})
        }

        # UUID-based ID to avoid millisecond collisions
        point_id = uuid.uuid4().int >> 64

        self.vector_store.upsert(
            collection_name=memory_type,
            vectors=[vector],
            payloads=[payload],
            ids=[point_id]
        )

        if self.event_bus:
            self.event_bus.emit_sync(Event(
                event_type=EventType.MEMORY_WRITE,
                component="memory_manager",
                trace_id="system",  # TODO: Get real trace_id
                payload={"type": memory_type, "importance": importance}
            ))

    def search(
        self,
        query: str,
        memory_type: Literal["episodic", "semantic"] = "episodic",
        limit: int = 5,
        recency_weight: float = 0.2,
        importance_weight: float = 0.3,
        similarity_weight: float = 0.5,
        filter_metadata: Optional[Dict[str, Any]] = None,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Search memory with weighted scoring.

        Args:
            query: Search string.
            memory_type: Collection to search.
            limit: Number of results.
            recency_weight: Weight for how recent the memory is.
            importance_weight: Weight for memory's importance field.
            similarity_weight: Weight for vector similarity score.
            filter_metadata: Optional metadata key-value pairs to filter results.
            min_score: Minimum total score threshold; results below are excluded.

        Returns:
            List of processed results.
        """
        if self.event_bus:
            self.event_bus.emit_sync(Event(
                event_type=EventType.MEMORY_QUERY,
                component="memory_manager",
                trace_id="system",
                payload={"query": query, "type": memory_type}
            ))

        vector_result = self.embedding_service.encode(query)

        # Type narrowing for mypy
        if isinstance(vector_result, list) and len(vector_result) > 0 and isinstance(vector_result[0], list):
            query_vector = cast(List[float], vector_result[0])
        else:
            query_vector = cast(List[float], vector_result)

        results = self.vector_store.query(
            collection_name=memory_type,
            query_vector=query_vector,
            limit=limit,
            filter_metadata=filter_metadata,
        )

        if not results:
            if self.event_bus:
                self.event_bus.emit_sync(Event(
                    event_type=EventType.MEMORY_MISS,
                    component="memory_manager",
                    trace_id="system",
                    payload={"query": query}
                ))
            return []

        processed_results = []
        now = time.time()

        for res in results:
            payload = res.payload
            similarity = res.score
            importance = payload.get("importance", 0.5)
            timestamp = payload.get("timestamp", now)

            # Recency: exponential decay with configured half-life
            age_seconds = now - timestamp
            half_life_seconds = self.recency_decay_days * 24 * 3600
            recency = math.exp(-0.693 * age_seconds / half_life_seconds)

            total_score = (
                (similarity * similarity_weight) +
                (recency * recency_weight) +
                (importance * importance_weight)
            )

            processed_results.append({
                "text": payload.get("text", ""),
                "score": total_score,
                "metadata": {k: v for k, v in payload.items() if k not in ["text", "importance", "timestamp"]},
                "timestamp": timestamp,
                "importance": importance,
                "similarity": similarity
            })

        # Sort by total score
        processed_results.sort(key=lambda x: x["score"], reverse=True)

        # Filter by minimum score threshold
        processed_results = [r for r in processed_results if r["score"] >= min_score]

        if self.event_bus:
            self.event_bus.emit_sync(Event(
                event_type=EventType.MEMORY_HIT,
                component="memory_manager",
                trace_id="system",
                payload={"count": len(processed_results)}
            ))

        return processed_results[:limit]
