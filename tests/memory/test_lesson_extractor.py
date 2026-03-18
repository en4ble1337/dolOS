"""Tests for LessonExtractor — lesson detection, dedup, file I/O, and telemetry."""

import os
import json
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from core.telemetry import EventBus, EventType
from memory.lesson_extractor import LessonExtractor


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate = AsyncMock()
    return llm


@pytest.fixture
def mock_memory():
    mem = MagicMock()
    mem.search = MagicMock(return_value=[])
    mem.add_memory = MagicMock()
    return mem


def _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path):
    return LessonExtractor(
        llm=mock_llm,
        memory=mock_memory,
        lessons_path=str(tmp_path / "LESSONS.md"),
        event_bus=mock_event_bus,
        similarity_threshold=0.90,
    )


def _make_llm_response(lessons: list) -> MagicMock:
    resp = MagicMock()
    resp.content = json.dumps(lessons)
    resp.tool_calls = None
    return resp


class TestLessonExtractor:
    @pytest.mark.asyncio
    async def test_lesson_extracted_from_correction(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)
        mock_llm.generate.return_value = _make_llm_response([
            {"title": "Use X not Y", "context": "User corrected format", "lesson": "Always use X"}
        ])

        count = await extractor.extract_and_store(
            user_message="No, use X instead",
            assistant_response="I used Y",
            session_id="s1",
            trace_id="t1",
        )

        assert count == 1
        lessons_file = tmp_path / "LESSONS.md"
        assert lessons_file.exists()
        content = lessons_file.read_text()
        assert "Use X not Y" in content
        mock_memory.add_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_lesson_when_llm_returns_empty(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)
        mock_llm.generate.return_value = _make_llm_response([])

        count = await extractor.extract_and_store("hi", "hello", "s1", "t1")

        assert count == 0
        mock_memory.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplication_skips_similar_lesson(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)
        mock_llm.generate.return_value = _make_llm_response([
            {"title": "Use X", "context": "ctx", "lesson": "use X"}
        ])
        # Simulate high-similarity hit in semantic memory
        mock_memory.search.return_value = [{"score": 0.95, "text": "use X always"}]

        count = await extractor.extract_and_store("No, use X", "I used Y", "s1", "t1")

        assert count == 0
        mock_memory.add_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_created_if_not_exists(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)
        mock_llm.generate.return_value = _make_llm_response([
            {"title": "First lesson", "context": "ctx", "lesson": "do this"}
        ])

        await extractor.extract_and_store("correct me", "oops", "s1", "t1")

        lessons_file = tmp_path / "LESSONS.md"
        assert lessons_file.exists()
        content = lessons_file.read_text()
        assert "# Agent Lessons Learned" in content

    @pytest.mark.asyncio
    async def test_malformed_json_is_parsed(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        """LLM returns markdown-fenced JSON — should still parse correctly."""
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)
        resp = MagicMock()
        resp.content = '```json\n[{"title": "T", "context": "C", "lesson": "L"}]\n```'
        resp.tool_calls = None
        mock_llm.generate.return_value = resp

        count = await extractor.extract_and_store("fix", "oops", "s1", "t1")
        assert count == 1

    @pytest.mark.asyncio
    async def test_llm_failure_emits_error_event(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)
        mock_llm.generate.side_effect = RuntimeError("LLM down")

        with pytest.raises(RuntimeError):
            await extractor.extract_and_store("msg", "resp", "s1", "t1")

        emitted = [c.args[0].event_type for c in mock_event_bus.emit.await_args_list]
        assert EventType.LESSON_EXTRACTION_ERROR in emitted

    @pytest.mark.asyncio
    async def test_telemetry_events_emitted(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)
        mock_llm.generate.return_value = _make_llm_response([
            {"title": "T", "context": "C", "lesson": "L"}
        ])

        await extractor.extract_and_store("msg", "resp", "s1", "t1")

        emitted = [c.args[0].event_type for c in mock_event_bus.emit.await_args_list]
        assert EventType.LESSON_EXTRACTION_START in emitted
        assert EventType.LESSON_EXTRACTION_COMPLETE in emitted

    @pytest.mark.asyncio
    async def test_empty_messages_skipped(self, mock_llm, mock_memory, mock_event_bus, tmp_path) -> None:
        extractor = _make_extractor(mock_llm, mock_memory, mock_event_bus, tmp_path)

        count = await extractor.extract_and_store("", "", "s1", "t1")

        assert count == 0
        mock_llm.generate.assert_not_called()
