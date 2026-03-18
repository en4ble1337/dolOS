"""Tests for the semantic memory extraction pipeline."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.llm import LLMResponse
from core.telemetry import EventBus, EventType
from memory.semantic_extractor import SemanticExtractor


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=LLMResponse(content='["User prefers dark mode", "User lives in NYC"]')
    )
    return llm


@pytest.fixture
def mock_memory() -> MagicMock:
    mem = MagicMock()
    mem.search.return_value = []  # No duplicates by default
    return mem


@pytest.fixture
def mock_event_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


@pytest.fixture
def extractor(mock_llm: MagicMock, mock_memory: MagicMock, mock_event_bus: MagicMock) -> SemanticExtractor:
    return SemanticExtractor(
        llm=mock_llm,
        memory=mock_memory,
        event_bus=mock_event_bus,
        similarity_threshold=0.85,
        default_importance=0.8,
    )


class TestExtractAndStore:
    @pytest.mark.asyncio
    async def test_basic_extraction(self, extractor: SemanticExtractor, mock_memory: MagicMock) -> None:
        stored = await extractor.extract_and_store(
            user_message="I prefer dark mode and I live in NYC",
            assistant_response="Noted! I'll remember your preferences.",
            session_id="s1",
            trace_id="t1",
        )

        assert stored == 2
        assert mock_memory.add_memory.call_count == 2

        # Verify first fact stored correctly
        first_call = mock_memory.add_memory.call_args_list[0]
        assert first_call.kwargs["text"] == "User prefers dark mode"
        assert first_call.kwargs["memory_type"] == "semantic"
        assert first_call.kwargs["importance"] == 0.8
        assert first_call.kwargs["metadata"]["source"] == "extraction"

    @pytest.mark.asyncio
    async def test_deduplication(
        self, extractor: SemanticExtractor, mock_memory: MagicMock
    ) -> None:
        # First fact is a duplicate (high similarity), second is not
        mock_memory.search.side_effect = [
            [{"text": "User prefers dark mode", "similarity": 0.95, "score": 0.95}],
            [],
        ]

        stored = await extractor.extract_and_store(
            user_message="I prefer dark mode and I live in NYC",
            assistant_response="Got it!",
            session_id="s1",
            trace_id="t1",
        )

        assert stored == 1
        assert mock_memory.add_memory.call_count == 1
        assert mock_memory.add_memory.call_args.kwargs["text"] == "User lives in NYC"

    @pytest.mark.asyncio
    async def test_no_facts_extracted(
        self, extractor: SemanticExtractor, mock_llm: MagicMock, mock_memory: MagicMock
    ) -> None:
        mock_llm.generate = AsyncMock(return_value=LLMResponse(content="[]"))

        stored = await extractor.extract_and_store(
            user_message="Hello!",
            assistant_response="Hi there!",
            session_id="s1",
            trace_id="t1",
        )

        assert stored == 0
        mock_memory.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_json_fallback(
        self, extractor: SemanticExtractor, mock_llm: MagicMock, mock_memory: MagicMock
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                content='Here are the facts:\n```json\n["User likes Python"]\n```'
            )
        )

        stored = await extractor.extract_and_store(
            user_message="I love Python",
            assistant_response="Great choice!",
            session_id="s1",
            trace_id="t1",
        )

        assert stored == 1
        assert mock_memory.add_memory.call_args.kwargs["text"] == "User likes Python"

    @pytest.mark.asyncio
    async def test_unparseable_response(
        self, extractor: SemanticExtractor, mock_llm: MagicMock, mock_memory: MagicMock
    ) -> None:
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(content="I don't have any facts to share")
        )

        stored = await extractor.extract_and_store(
            user_message="Hi",
            assistant_response="Hello",
            session_id="s1",
            trace_id="t1",
        )

        assert stored == 0
        mock_memory.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(
        self, extractor: SemanticExtractor, mock_llm: MagicMock, mock_event_bus: MagicMock
    ) -> None:
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))

        with pytest.raises(RuntimeError, match="LLM down"):
            await extractor.extract_and_store(
                user_message="test",
                assistant_response="test",
                session_id="s1",
                trace_id="t1",
            )

        # Verify error telemetry emitted
        error_events = [
            call.args[0]
            for call in mock_event_bus.emit_sync.call_args_list
            if call.args[0].event_type == EventType.SEMANTIC_EXTRACTION_ERROR
        ]
        assert len(error_events) == 1

    @pytest.mark.asyncio
    async def test_threshold_configurable(
        self, mock_llm: MagicMock, mock_memory: MagicMock
    ) -> None:
        extractor = SemanticExtractor(
            llm=mock_llm,
            memory=mock_memory,
            similarity_threshold=0.95,
        )

        # Similarity of 0.90 is below threshold of 0.95 — not a duplicate
        mock_memory.search.return_value = [
            {"text": "User prefers dark mode", "similarity": 0.90, "score": 0.90}
        ]

        stored = await extractor.extract_and_store(
            user_message="I prefer dark mode",
            assistant_response="Noted",
            session_id="s1",
            trace_id="t1",
        )

        assert stored == 2  # Both facts stored since threshold is higher

    @pytest.mark.asyncio
    async def test_empty_messages_skipped(self, extractor: SemanticExtractor) -> None:
        stored = await extractor.extract_and_store(
            user_message="   ",
            assistant_response="",
            session_id="s1",
            trace_id="t1",
        )
        assert stored == 0

    @pytest.mark.asyncio
    async def test_telemetry_events_emitted(
        self, extractor: SemanticExtractor, mock_event_bus: MagicMock
    ) -> None:
        await extractor.extract_and_store(
            user_message="I use Python 3.11",
            assistant_response="Good version!",
            session_id="s1",
            trace_id="t1",
        )

        event_types = [
            call.args[0].event_type for call in mock_event_bus.emit_sync.call_args_list
        ]
        assert EventType.SEMANTIC_EXTRACTION_START in event_types
        assert EventType.SEMANTIC_EXTRACTION_COMPLETE in event_types
