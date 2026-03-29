import time
from typing import Any

import pytest

from memory.vector_store import VectorStore


@pytest.fixture
def vector_store() -> VectorStore:
    # Setup VectorStore with an in-memory Qdrant instance
    return VectorStore(location=":memory:")


def test_vector_store_initialization(vector_store: VectorStore) -> None:
    assert vector_store is not None
    assert vector_store.client is not None


def test_create_collection(vector_store: VectorStore) -> None:
    collection_name = "test_collection"
    vector_size = 384

    # Create the collection
    vector_store.create_collection(collection_name, vector_size)

    # Check if collection exists
    assert vector_store.collection_exists(collection_name) is True


def test_upsert_and_query(vector_store: VectorStore) -> None:
    collection_name = "test_data"
    vector_store.create_collection(collection_name, 3)

    # Upsert a point
    vectors = [[0.1, 0.2, 0.3]]
    payloads = [{"id": "doc1", "text": "Hello world", "importance": 0.8}]
    ids: Any = [1]

    vector_store.upsert(collection_name, vectors, payloads, ids)

    # Query the point
    query_vector = [0.1, 0.2, 0.3]
    results = vector_store.query(collection_name, query_vector, limit=1)

    assert len(results) == 1
    assert results[0].payload["id"] == "doc1"
    assert results[0].payload["text"] == "Hello world"
    assert results[0].score > 0.9  # Should be high similarity


def test_query_with_metadata_filter(vector_store: VectorStore) -> None:
    collection_name = "test_filters"
    vector_store.create_collection(collection_name, 3)

    vectors = [
        [0.1, 0.2, 0.3],
        [0.2, 0.3, 0.4]
    ]
    payloads = [
        {"id": "doc1", "category": "A"},
        {"id": "doc2", "category": "B"}
    ]
    ids: Any = [1, 2]

    vector_store.upsert(collection_name, vectors, payloads, ids)

    # Query with filter
    query_vector = [0.15, 0.25, 0.35]

    # We want to match only category B
    results = vector_store.query(
        collection_name,
        query_vector,
        limit=10,
        filter_metadata={"category": "B"}
    )

    assert len(results) == 1
    assert results[0].payload["id"] == "doc2"


def test_delete_by_filter_removes_old_low_importance(vector_store: VectorStore) -> None:
    """Only old + low-importance points should be deleted; others remain."""
    collection_name = "test_delete_filter"
    vector_store.create_collection(collection_name, 3)

    now = time.time()
    old_ts = now - 10_000   # well in the past
    recent_ts = now          # right now

    # Point 1: old + low importance  → should be deleted
    # Point 2: old + high importance → should remain
    # Point 3: recent + low importance → should remain
    vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]
    payloads: Any = [
        {"text": "old low", "timestamp": old_ts, "importance": 0.1},
        {"text": "old high", "timestamp": old_ts, "importance": 0.9},
        {"text": "recent low", "timestamp": recent_ts, "importance": 0.1},
    ]
    ids: Any = [10, 20, 30]
    vector_store.upsert(collection_name, vectors, payloads, ids)

    # Delete entries older than (now - 1 second) with importance < 0.3
    cutoff = now - 1
    vector_store.delete_by_filter(
        collection_name=collection_name,
        before_timestamp=cutoff,
        max_importance=0.3,
    )

    # Query all remaining points with a broad vector search
    remaining = vector_store.query(collection_name, [0.1, 0.2, 0.3], limit=10)
    remaining_texts = [r.payload.get("text") for r in remaining]

    assert "old low" not in remaining_texts, "old+low-importance point should have been deleted"
    assert "old high" in remaining_texts, "old+high-importance point should remain"
    assert "recent low" in remaining_texts, "recent+low-importance point should remain"


def test_file_backed_persistence(tmp_path: Any) -> None:
    storage_path = str(tmp_path / "qdrant_test")

    # Create store, insert data, then close
    store1 = VectorStore(location=storage_path)
    store1.create_collection("persist_test", 3)
    store1.upsert(
        "persist_test",
        vectors=[[0.1, 0.2, 0.3]],
        payloads=[{"text": "I survive restarts"}],
        ids=[1],
    )
    store1.client.close()

    # Reopen from same path — data should still be there
    store2 = VectorStore(location=storage_path)
    results = store2.query("persist_test", [0.1, 0.2, 0.3], limit=1)

    assert len(results) == 1
    assert results[0].payload["text"] == "I survive restarts"
    store2.client.close()
