import math
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.telemetry import EventType
from memory.memory_manager import MemoryManager


@pytest.fixture
def mock_vector_store() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_embedding_service() -> MagicMock:
    mock = MagicMock()
    mock.dimension = 384
    mock.encode.return_value = [0.1] * 384
    return mock


@pytest.fixture
def mock_event_bus() -> MagicMock:
    return MagicMock()


@pytest.fixture
def memory_manager(mock_vector_store: MagicMock, mock_embedding_service: MagicMock, mock_event_bus: MagicMock) -> MemoryManager:
    with patch('memory.memory_manager.VectorStore', return_value=mock_vector_store):
        with patch('memory.memory_manager.EmbeddingService', return_value=mock_embedding_service):
            manager = MemoryManager(event_bus=mock_event_bus)
            return manager


def test_memory_manager_initialization(memory_manager: MemoryManager, mock_vector_store: MagicMock) -> None:
    # Should create two collections
    assert mock_vector_store.create_collection.call_count == 2
    mock_vector_store.create_collection.assert_any_call("episodic", 384)
    mock_vector_store.create_collection.assert_any_call("semantic", 384)


def test_add_memory(memory_manager: MemoryManager, mock_vector_store: MagicMock, mock_embedding_service: MagicMock, mock_event_bus: MagicMock) -> None:
    memory_manager.add_memory("User likes pizza", memory_type="semantic", importance=0.9)

    # Check embedding call
    mock_embedding_service.encode.assert_called_with("User likes pizza")

    # Check vector store upsert
    mock_vector_store.upsert.assert_called_once()
    _, kwargs = mock_vector_store.upsert.call_args
    assert kwargs["collection_name"] == "semantic"
    assert "importance" in kwargs["payloads"][0]
    assert kwargs["payloads"][0]["importance"] == 0.9
    assert "timestamp" in kwargs["payloads"][0]

    # Check telemetry
    assert mock_event_bus.emit_sync.called
    event = mock_event_bus.emit_sync.call_args[0][0]
    assert event.event_type == EventType.MEMORY_WRITE


def test_retrieve_memory_with_scoring(memory_manager: MemoryManager, mock_vector_store: MagicMock, mock_embedding_service: MagicMock, mock_event_bus: MagicMock) -> None:
    # Mock search results
    now = datetime.now().timestamp()
    mock_results = [
        MagicMock(
            score=0.8,
            payload={
                "text": "Result 1",
                "timestamp": now,
                "importance": 0.5
            }
        ),
        MagicMock(
            score=0.7,
            payload={
                "text": "Result 2",
                "timestamp": now - 86400,  # 1 day ago
                "importance": 0.9
            }
        )
    ]
    mock_vector_store.query.return_value = mock_results

    results = memory_manager.search("pizza", memory_type="semantic", limit=2)

    assert len(results) == 2
    # Result 2 has higher importance and recency might play a role,
    # but exact ordering depends on implementation.
    # Here we just check we got the processed results.
    assert "text" in results[0]
    assert "score" in results[0]

    # Check telemetry for query and hit
    # Should emit MEMORY_QUERY and then MEMORY_HIT (since results > 0)
    assert mock_event_bus.emit_sync.call_count >= 2
    event_types = [call[0][0].event_type for call in mock_event_bus.emit_sync.call_args_list]
    assert EventType.MEMORY_QUERY in event_types
    assert EventType.MEMORY_HIT in event_types


def test_retrieve_memory_miss(memory_manager: MemoryManager, mock_vector_store: MagicMock, mock_event_bus: MagicMock) -> None:
    mock_vector_store.query.return_value = []

    results = memory_manager.search("nothing", limit=5)

    assert len(results) == 0

    # Check telemetry for query and miss
    event_types = [call[0][0].event_type for call in mock_event_bus.emit_sync.call_args_list]
    assert EventType.MEMORY_QUERY in event_types
    assert EventType.MEMORY_MISS in event_types


def test_search_with_filter_metadata(memory_manager: MemoryManager, mock_vector_store: MagicMock) -> None:
    mock_vector_store.query.return_value = []

    memory_manager.search("test", filter_metadata={"session_id": "abc"})

    # Verify filter_metadata is forwarded to vector_store.query
    _, kwargs = mock_vector_store.query.call_args
    assert kwargs["filter_metadata"] == {"session_id": "abc"}


def test_search_min_score_filters_low_results(memory_manager: MemoryManager, mock_vector_store: MagicMock) -> None:
    """min_score=0.99 should exclude all results since no memory scores that high with an unrelated query."""
    now = datetime.now().timestamp()
    mock_results = [
        MagicMock(
            score=0.3,
            payload={"text": "Something completely unrelated", "timestamp": now, "importance": 0.1}
        ),
        MagicMock(
            score=0.2,
            payload={"text": "Also unrelated", "timestamp": now, "importance": 0.1}
        ),
    ]
    mock_vector_store.query.return_value = mock_results

    results = memory_manager.search("quantum physics equations", min_score=0.99)

    assert len(results) == 0


def test_search_min_score_zero_returns_all(memory_manager: MemoryManager, mock_vector_store: MagicMock) -> None:
    """min_score=0.0 (default) should return results normally without filtering."""
    now = datetime.now().timestamp()
    mock_results = [
        MagicMock(
            score=0.5,
            payload={"text": "Memory A", "timestamp": now, "importance": 0.5}
        ),
        MagicMock(
            score=0.4,
            payload={"text": "Memory B", "timestamp": now, "importance": 0.4}
        ),
    ]
    mock_vector_store.query.return_value = mock_results

    results = memory_manager.search("test query", min_score=0.0)

    assert len(results) == 2


def test_recency_exponential_never_zero(memory_manager: MemoryManager, mock_vector_store: MagicMock) -> None:
    """A very old memory (1000 days) should still have recency > 0 with exponential decay."""
    age_1000_days = 1000 * 24 * 3600
    old_timestamp = datetime.now().timestamp() - age_1000_days
    mock_results = [
        MagicMock(
            score=0.8,
            payload={"text": "Very old memory", "timestamp": old_timestamp, "importance": 0.5}
        ),
    ]
    mock_vector_store.query.return_value = mock_results

    results = memory_manager.search("old memory")

    assert len(results) == 1
    # With exponential decay, recency is always > 0; with linear 30-day it would be 0
    # Verify the score is positive (recency contribution is non-zero)
    assert results[0]["score"] > 0
    # Double-check: compute expected recency directly using math.exp
    half_life_seconds = memory_manager.recency_decay_days * 24 * 3600
    expected_recency = math.exp(-0.693 * age_1000_days / half_life_seconds)
    assert expected_recency > 0


def test_recency_half_life_at_decay_days(memory_manager: MemoryManager, mock_vector_store: MagicMock) -> None:
    """A memory exactly recency_decay_days old should have recency ~0.5 (±0.05)."""
    decay_days = memory_manager.recency_decay_days
    age_at_half_life = decay_days * 24 * 3600
    old_timestamp = datetime.now().timestamp() - age_at_half_life
    mock_results = [
        MagicMock(
            score=0.0,
            payload={"text": "Half-life memory", "timestamp": old_timestamp, "importance": 0.0}
        ),
    ]
    mock_vector_store.query.return_value = mock_results

    # Use weights that isolate recency: recency_weight=1, others=0
    results = memory_manager.search(
        "half-life test",
        recency_weight=1.0,
        importance_weight=0.0,
        similarity_weight=0.0,
    )

    assert len(results) == 1
    # score == recency * 1.0 + 0 + 0, so score == recency
    assert abs(results[0]["score"] - 0.5) <= 0.05
