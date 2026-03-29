"""MemoryMaintenanceTask — weekly heartbeat integration that evicts old, low-importance
episodic memories to prevent unbounded growth.
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
    """Heartbeat integration that periodically evicts stale episodic memories.

    Deletes entries from the ``episodic`` collection that are both older than
    ``retention_days`` and below the ``max_importance`` threshold.
    """

    name: str = "memory_maintenance"

    def __init__(
        self,
        event_bus: EventBus,
        vector_store: VectorStore,
        retention_days: int = 60,
        max_importance: float = 0.3,
    ) -> None:
        super().__init__(event_bus)
        self.vector_store = vector_store
        self.retention_days = retention_days
        self.max_importance = max_importance

    async def check(self) -> dict[str, Any]:
        """Delete episodic entries older than retention_days with importance < max_importance."""
        cutoff = time.time() - (self.retention_days * 86400)
        deleted = self.vector_store.delete_by_filter(
            collection_name="episodic",
            before_timestamp=cutoff,
            max_importance=self.max_importance,
        )
        logger.info(
            "MemoryMaintenance: deleted %d old low-importance episodic entries",
            deleted,
        )
        return {"deleted": deleted, "retention_days": self.retention_days, "cutoff": cutoff}
