import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Sequence, cast

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    Range,
    VectorParams,
)

logger = logging.getLogger(__name__)


class VectorStore:
    """Wrapper around Qdrant client for vector search operations."""

    def __init__(self, location: str = ":memory:", **kwargs: Any) -> None:
        """Initialize Qdrant client.

        Args:
            location: Storage location (":memory:", path to db, or URL).
            **kwargs: Additional client arguments.
        """
        if location != ":memory:" and not location.startswith("http"):
            os.makedirs(location, exist_ok=True)
            try:
                self.client = QdrantClient(path=location, **kwargs)
            except Exception as e:
                logger.warning(
                    "Qdrant storage at '%s' appears corrupted (%s). "
                    "Resetting to fresh storage.",
                    location, e,
                )
                shutil.rmtree(location)
                os.makedirs(location, exist_ok=True)
                self.client = QdrantClient(path=location, **kwargs)
        else:
            self.client = QdrantClient(location=location, **kwargs)

    def create_collection(self, collection_name: str, vector_size: int, distance: Distance = Distance.COSINE) -> None:
        """Create a new collection if it doesn't exist.

        Args:
            collection_name: Name of the collection.
            vector_size: Dimension of the vectors.
            distance: Similarity metric.
        """
        if not self.collection_exists(collection_name):
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=distance),
            )

    def collection_exists(self, collection_name: str) -> bool:
        """Check if a collection exists."""
        collections = self.client.get_collections().collections
        return any(c.name == collection_name for c in collections)

    def upsert(
        self,
        collection_name: str,
        vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
        ids: Optional[Sequence[str | int]] = None
    ) -> None:
        """Upsert vectors and payloads into a collection.

        Args:
            collection_name: Name of the collection.
            vectors: List of embedding vectors.
            payloads: List of associated metadata.
            ids: Optional list of unique IDs.
        """
        points = []
        for i, vector in enumerate(vectors):
            point_id = ids[i] if ids else i
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payloads[i]
                )
            )

        self.client.upsert(
            collection_name=collection_name,
            points=points
        )

    def query(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Any]:
        """Search for similar vectors.

        Args:
            collection_name: Name of the collection.
            query_vector: The vector to search with.
            limit: Maximum number of results.
            filter_metadata: Metadata key-value pairs to filter by.

        Returns:
            List of search results with score and payload.
        """
        query_filter = None
        if filter_metadata:
            conditions: Any = [
                FieldCondition(key=key, match=MatchValue(value=value))
                for key, value in filter_metadata.items()
            ]
            query_filter = Filter(must=conditions)

        # In newer qdrant-client versions, search is replaced by query_points
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                query_filter=query_filter
            )
            return cast(List[Any], response.points)

        # Fallback for older versions if search exists
        search_func = getattr(self.client, "search", None)
        if search_func:
            return cast(List[Any], search_func(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter
            ))
        
        return []

    def delete_by_filter(
        self,
        collection_name: str,
        before_timestamp: float,
        max_importance: float,
    ) -> int:
        """Delete episodic entries older than before_timestamp with importance below max_importance.

        Returns count of deleted points (operation_id as proxy; Qdrant does not
        return an exact deleted count on filter-based deletes).
        """
        filter_condition = Filter(
            must=[
                FieldCondition(key="timestamp", range=Range(lt=before_timestamp)),
                FieldCondition(key="importance", range=Range(lt=max_importance)),
            ]
        )
        result = self.client.delete(
            collection_name=collection_name,
            points_selector=FilterSelector(filter=filter_condition),
        )
        # result.status == "acknowledged" on success; operation_id is a proxy count
        return result.operation_id or 0
