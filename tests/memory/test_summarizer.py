"""Tests for the conversation summarizer."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm import LLMResponse
from core.telemetry import EventBus, EventType
from memory.summarizer import ConversationSummarizer


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=LLMResponse(
            content="User discussed Python project setup and decided on FastAPI."
        )
    )
    return llm


@pytest.fixture
def mock_memory() -> MagicMock:
    mem = MagicMock()
    mem.search.return_value = []
    return mem


@pytest.fixture
def mock_event_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


@pytest.fixture
def summarizer(
    mock_llm: MagicMock, mock_memory: MagicMock, mock_event_bus: MagicMock
) -> ConversationSummarizer:
    return ConversationSummarizer(
        llm=mock_llm,
        memory=mock_memory,
        event_bus=mock_event_bus,
        turn_threshold=10,
        summary_importance=0.9,
    )


class TestIncrementTurn:
    def test_below_threshold(self, summarizer: ConversationSummarizer) -> None:
        for _ in range(9):
            assert summarizer.increment_turn("session1") is False

    def test_at_threshold(self, summarizer: ConversationSummarizer) -> None:
        for _ in range(9):
            summarizer.increment_turn("session1")
        assert summarizer.increment_turn("session1") is True

    def test_resets_after_threshold(self, summarizer: ConversationSummarizer) -> None:
        for _ in range(10):
            summarizer.increment_turn("session1")
        # Counter should have reset — next call starts at 1
        assert summarizer.increment_turn("session1") is False

    def test_independent_session_counters(self, summarizer: ConversationSummarizer) -> None:
        for _ in range(5):
            summarizer.increment_turn("session_a")
        for _ in range(9):
            summarizer.increment_turn("session_b")

        assert summarizer.increment_turn("session_a") is False  # 6th
        assert summarizer.increment_turn("session_b") is True  # 10th


class TestSummarizeSession:
    @pytest.mark.asyncio
    async def test_summarize_session(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock, mock_llm: MagicMock
    ) -> None:
        now = time.time()
        mock_memory.search.return_value = [
            {"text": "User: How do I set up FastAPI?", "timestamp": now - 300, "metadata": {}},
            {"text": "Assistant: Install it with pip install fastapi.", "timestamp": now - 200, "metadata": {}},
            {"text": "User: What about uvicorn?", "timestamp": now - 100, "metadata": {}},
        ]

        result = await summarizer.summarize_session("s1", "t1")

        assert result is not None
        assert "FastAPI" in result
        mock_llm.generate.assert_called_once()

        # Verify summary stored with correct metadata
        mock_memory.add_memory.assert_called_once()
        call_kwargs = mock_memory.add_memory.call_args.kwargs
        assert call_kwargs["memory_type"] == "episodic"
        assert call_kwargs["importance"] == 0.9
        assert call_kwargs["metadata"]["is_summary"] is True
        assert call_kwargs["metadata"]["session_id"] == "s1"
        assert call_kwargs["metadata"]["summarized_turn_count"] == 3

    @pytest.mark.asyncio
    async def test_summarize_no_memories(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock, mock_llm: MagicMock
    ) -> None:
        mock_memory.search.return_value = []

        result = await summarizer.summarize_session("s1", "t1")

        assert result is None
        mock_llm.generate.assert_not_called()
        mock_memory.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_summarize_too_few_memories(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock, mock_llm: MagicMock
    ) -> None:
        mock_memory.search.return_value = [
            {"text": "User: Hi", "timestamp": time.time(), "metadata": {}},
            {"text": "Assistant: Hello", "timestamp": time.time(), "metadata": {}},
        ]

        result = await summarizer.summarize_session("s1", "t1")

        assert result is None
        mock_llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_summarize_filters_existing_summaries(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock
    ) -> None:
        now = time.time()
        mock_memory.search.return_value = [
            {"text": "User: First message", "timestamp": now - 300, "metadata": {}},
            {"text": "Old summary text", "timestamp": now - 200, "metadata": {"is_summary": True}},
            {"text": "User: Second message", "timestamp": now - 100, "metadata": {}},
        ]

        # Only 2 non-summary memories — below threshold of 3
        result = await summarizer.summarize_session("s1", "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_llm_failure(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock,
        mock_llm: MagicMock, mock_event_bus: MagicMock
    ) -> None:
        now = time.time()
        mock_memory.search.return_value = [
            {"text": f"Turn {i}", "timestamp": now - i, "metadata": {}}
            for i in range(5)
        ]
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))

        with pytest.raises(RuntimeError, match="LLM down"):
            await summarizer.summarize_session("s1", "t1")

        error_events = [
            call.args[0]
            for call in mock_event_bus.emit_sync.call_args_list
            if call.args[0].event_type == EventType.SUMMARIZATION_ERROR
        ]
        assert len(error_events) == 1

    @pytest.mark.asyncio
    async def test_telemetry_emitted(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock,
        mock_event_bus: MagicMock
    ) -> None:
        now = time.time()
        mock_memory.search.return_value = [
            {"text": f"Turn {i}", "timestamp": now - i, "metadata": {}}
            for i in range(5)
        ]

        await summarizer.summarize_session("s1", "t1")

        event_types = [
            call.args[0].event_type for call in mock_event_bus.emit_sync.call_args_list
        ]
        assert EventType.SUMMARIZATION_START in event_types
        assert EventType.SUMMARIZATION_COMPLETE in event_types


    @pytest.mark.asyncio
    async def test_summarize_does_not_use_summary_phrase_as_query(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock
    ) -> None:
        """The search query must NOT be 'conversation summary' — that phrase biases
        vector search toward summary-like text and excludes ordinary chat turns."""
        now = time.time()
        mock_memory.search.return_value = [
            {"text": "User: How do I set up FastAPI?", "timestamp": now - 300, "metadata": {}},
            {"text": "Assistant: Install it with pip install fastapi.", "timestamp": now - 200, "metadata": {}},
            {"text": "User: What about uvicorn?", "timestamp": now - 100, "metadata": {}},
        ]

        await summarizer.summarize_session("s1", "t1")

        call_kwargs = mock_memory.search.call_args.kwargs
        assert call_kwargs["query"] != "conversation summary", (
            "summarize_session must not use 'conversation summary' as the search query "
            "because it biases vector retrieval away from ordinary chat turns."
        )


class TestGetSessionSummary:
    def test_summary_exists(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock
    ) -> None:
        mock_memory.search.return_value = [
            {"text": "Previous summary of the conversation.", "score": 0.9}
        ]

        result = summarizer.get_session_summary("s1")

        assert result == "Previous summary of the conversation."
        # Verify filter_metadata was passed
        call_kwargs = mock_memory.search.call_args.kwargs
        assert call_kwargs["filter_metadata"]["session_id"] == "s1"
        assert call_kwargs["filter_metadata"]["is_summary"] is True

    def test_no_summary(
        self, summarizer: ConversationSummarizer, mock_memory: MagicMock
    ) -> None:
        mock_memory.search.return_value = []

        result = summarizer.get_session_summary("s1")
        assert result is None
