"""Tests for LessonExtractor integration in Agent."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent import Agent
from core.telemetry import EventBus
from memory.lesson_extractor import LessonExtractor


def _make_agent(tmp_path, lesson_extractor=None):
    mock_llm = MagicMock()
    resp = MagicMock()
    resp.content = "Agent response"
    resp.tool_calls = None
    mock_llm.generate = AsyncMock(return_value=resp)

    mock_memory = MagicMock()
    mock_memory.search = MagicMock(return_value=[])
    mock_memory.add_memory = MagicMock()

    mock_bus = MagicMock(spec=EventBus)
    mock_bus.emit = AsyncMock()

    agent = Agent(
        llm=mock_llm,
        memory=mock_memory,
        event_bus=mock_bus,
        lesson_extractor=lesson_extractor,
    )
    return agent, tmp_path


class TestAgentLearning:
    @pytest.mark.asyncio
    async def test_lessons_injected_into_system_prompt(self, tmp_path) -> None:
        lessons_file = tmp_path / "LESSONS.md"
        lessons_file.write_text("# Agent Lessons Learned\n\n## [2026-03-18] Use X\n**Lesson:** Always use X\n\n---\n")

        agent, _ = _make_agent(tmp_path)
        agent._lessons_path = str(lessons_file)

        with patch.object(agent, "_lessons_path", str(lessons_file)):
            await agent.process_message("s1", "hello")

        call_args = agent.llm.generate.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        system_prompt = messages[0]["content"]
        assert "<lessons_learned>" in system_prompt

    @pytest.mark.asyncio
    async def test_lessons_not_injected_when_file_missing(self, tmp_path) -> None:
        agent, _ = _make_agent(tmp_path)
        agent._lessons_path = str(tmp_path / "NONEXISTENT.md")

        await agent.process_message("s1", "hello")

        call_args = agent.llm.generate.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        system_prompt = messages[0]["content"]
        assert "<lessons_learned>" not in system_prompt

    @pytest.mark.asyncio
    async def test_lessons_not_injected_when_file_empty(self, tmp_path) -> None:
        lessons_file = tmp_path / "LESSONS.md"
        lessons_file.write_text("")

        agent, _ = _make_agent(tmp_path)
        agent._lessons_path = str(lessons_file)

        await agent.process_message("s1", "hello")

        call_args = agent.llm.generate.call_args
        messages = call_args[1]["messages"] if "messages" in call_args[1] else call_args[0][0]
        system_prompt = messages[0]["content"]
        assert "<lessons_learned>" not in system_prompt

    @pytest.mark.asyncio
    async def test_lesson_extraction_scheduled_as_background_task(self, tmp_path) -> None:
        mock_extractor = MagicMock(spec=LessonExtractor)
        mock_extractor.extract_and_store = AsyncMock(return_value=0)

        agent, _ = _make_agent(tmp_path, lesson_extractor=mock_extractor)

        await agent.process_message("s1", "hello")
        # Allow background tasks to run
        import asyncio
        await asyncio.sleep(0)

        mock_extractor.extract_and_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_lesson_extractor_optional(self, tmp_path) -> None:
        """Agent with lesson_extractor=None works normally."""
        agent, _ = _make_agent(tmp_path, lesson_extractor=None)
        result = await agent.process_message("s1", "hello")
        assert result == "Agent response"
