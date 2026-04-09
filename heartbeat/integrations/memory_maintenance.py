"""MemoryMaintenanceTask — weekly heartbeat integration that evicts old, low-importance
episodic memories to prevent unbounded growth, and prunes stale semantic memories.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.telemetry import EventBus
from heartbeat.integrations.base import HeartbeatIntegration
from memory.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryMaintenanceTask(HeartbeatIntegration):
    """Heartbeat integration that periodically evicts stale episodic and semantic memories.

    Episodic eviction:
        Deletes entries from the ``episodic`` collection that are both older than
        ``retention_days`` and below the ``max_importance`` threshold.

    Semantic eviction (two passes):
        1. Age-based: entries older than ``semantic_retention_days`` and below
           ``max_importance`` are evicted.
        2. Count-based: if the semantic collection exceeds ``max_semantic_count`` entries,
           a second pass evicts all low-importance entries regardless of age (using
           ``before_timestamp=now`` to cover the full collection).
    """

    name: str = "memory_maintenance"

    def __init__(
        self,
        event_bus: EventBus,
        vector_store: VectorStore,
        retention_days: int = 60,
        max_importance: float = 0.3,
        max_semantic_count: int = 5000,
        semantic_retention_days: int = 365,
    ) -> None:
        super().__init__(event_bus)
        self.vector_store = vector_store
        self.retention_days = retention_days
        self.max_importance = max_importance
        self.max_semantic_count = max_semantic_count
        self.semantic_retention_days = semantic_retention_days

    def _count_collection(self, collection_name: str) -> int:
        """Return the number of entries in *collection_name*, or 0 on error."""
        try:
            result = self.vector_store.client.count(collection_name=collection_name)
            count = result.count
            return count if isinstance(count, int) else 0
        except Exception:
            return 0

    async def check(self) -> dict[str, Any]:
        """Evict stale episodic entries, then prune old/excess semantic entries."""
        now = time.time()

        # --- Episodic eviction (existing behaviour) ---
        episodic_cutoff = now - (self.retention_days * 86400)
        episodic_deleted = self.vector_store.delete_by_filter(
            collection_name="episodic",
            before_timestamp=episodic_cutoff,
            max_importance=self.max_importance,
        )
        logger.info(
            "MemoryMaintenance: deleted %d old low-importance episodic entries",
            episodic_deleted,
        )

        # --- Semantic eviction: age-based pass ---
        semantic_cutoff = now - (self.semantic_retention_days * 86400)
        semantic_deleted = self.vector_store.delete_by_filter(
            collection_name="semantic",
            before_timestamp=semantic_cutoff,
            max_importance=self.max_importance,
        )

        # --- Semantic eviction: count-based pass ---
        semantic_count_deleted = 0
        current_count = self._count_collection("semantic")
        if current_count > self.max_semantic_count:
            # Evict any low-importance semantic entry (before_timestamp=now covers all)
            semantic_count_deleted = self.vector_store.delete_by_filter(
                collection_name="semantic",
                before_timestamp=now,
                max_importance=self.max_importance,
            )
            logger.info(
                "MemoryMaintenance: semantic count %d > limit %d; evicted %d low-importance entries",
                current_count,
                self.max_semantic_count,
                semantic_count_deleted,
            )

        semantic_total = semantic_deleted + semantic_count_deleted
        logger.info(
            "MemoryMaintenance: deleted %d stale semantic entries (%d age-based, %d count-based)",
            semantic_total,
            semantic_deleted,
            semantic_count_deleted,
        )

        return {
            "deleted": episodic_deleted,
            "retention_days": self.retention_days,
            "cutoff": episodic_cutoff,
            "semantic_deleted": semantic_total,
            "semantic_age_deleted": semantic_deleted,
            "semantic_count_deleted": semantic_count_deleted,
        }
