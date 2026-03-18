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
