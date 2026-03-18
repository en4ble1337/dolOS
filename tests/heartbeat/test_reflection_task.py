"""Tests for ReflectionTask heartbeat integration."""

import os
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from core.telemetry import EventBus, EventType
from heartbeat.integrations.reflection_task import ReflectionTask


@pytest.fixture
def mock_event_bus():
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    resp = MagicMock()
    resp.content = "# Agent Lessons Learned\n\n## [2026-03-17] Consolidated lesson\n**Context:** merged\n**Lesson:** do this\n\n---\n"
    llm.generate = AsyncMock(return_value=resp)
    return llm


def _make_lessons_content(n: int) -> str:
    lines = ["# Agent Lessons Learned\n\n"]
    for i in range(n):
        lines.append(f"## [2026-03-17] Lesson {i}\n**Context:** ctx\n**Lesson:** do x\n\n---\n\n")
    return "".join(lines)


class TestReflectionTaskCountLessons:
    def test_count_lessons_empty_file(self, mock_event_bus):
        task = ReflectionTask(llm=MagicMock(), event_bus=mock_event_bus)
        assert task._count_lessons("") == 0

    def test_count_lessons_counts_headers(self, mock_event_bus):
        content = _make_lessons_content(3)
        task = ReflectionTask(llm=MagicMock(), event_bus=mock_event_bus)
        assert task._count_lessons(content) == 3


class TestReflectionTaskCheck:
    @pytest.mark.asyncio
    async def test_skips_consolidation_below_threshold(self, mock_event_bus, mock_llm, tmp_path):
        lessons_file = tmp_path / "LESSONS.md"
        lessons_file.write_text(_make_lessons_content(5))

        task = ReflectionTask(
            llm=mock_llm,
            event_bus=mock_event_bus,
            lessons_path=str(lessons_file),
            consolidation_threshold=20,
        )
        result = await task.check()

        assert result["status"] == "skipped"
        assert result["lesson_count"] == 5
        mock_llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_consolidation_at_threshold(self, mock_event_bus, mock_llm, tmp_path):
        lessons_file = tmp_path / "LESSONS.md"
        lessons_file.write_text(_make_lessons_content(25))

        task = ReflectionTask(
            llm=mock_llm,
            event_bus=mock_event_bus,
            lessons_path=str(lessons_file),
            consolidation_threshold=20,
        )
        result = await task.check()

        assert result["status"] == "consolidated"
        assert result["lesson_count"] == 25
        mock_llm.generate.assert_called_once()
        # File should be rewritten with consolidated content
        new_content = lessons_file.read_text()
        assert "Consolidated lesson" in new_content

    @pytest.mark.asyncio
    async def test_file_not_found_returns_skipped(self, mock_event_bus, mock_llm, tmp_path):
        task = ReflectionTask(
            llm=mock_llm,
            event_bus=mock_event_bus,
            lessons_path=str(tmp_path / "NONEXISTENT.md"),
            consolidation_threshold=20,
        )
        result = await task.check()

        assert result["status"] == "skipped"
        assert result["lesson_count"] == 0
        mock_llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_telemetry_events_emitted(self, mock_event_bus, mock_llm, tmp_path):
        lessons_file = tmp_path / "LESSONS.md"
        lessons_file.write_text(_make_lessons_content(25))

        task = ReflectionTask(
            llm=mock_llm,
            event_bus=mock_event_bus,
            lessons_path=str(lessons_file),
            consolidation_threshold=20,
        )
        await task.check()

        emitted_types = [call.args[0].event_type for call in mock_event_bus.emit.await_args_list]
        assert EventType.REFLECTION_START in emitted_types
        assert EventType.REFLECTION_COMPLETE in emitted_types

    @pytest.mark.asyncio
    async def test_llm_failure_is_propagated(self, mock_event_bus, tmp_path):
        lessons_file = tmp_path / "LESSONS.md"
        original_content = _make_lessons_content(25)
        lessons_file.write_text(original_content)

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        task = ReflectionTask(
            llm=mock_llm,
            event_bus=mock_event_bus,
            lessons_path=str(lessons_file),
            consolidation_threshold=20,
        )

        with pytest.raises(RuntimeError, match="LLM unavailable"):
            await task.check()

        # File must remain unchanged
        assert lessons_file.read_text() == original_content
