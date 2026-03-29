"""Tests for CombinedTurnExtractor."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.combined_extractor import CombinedTurnExtractor, _parse_combined_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_response(content: str) -> MagicMock:
    """Return a mock LLMResponse with the given content."""
    resp = MagicMock()
    resp.content = content
    return resp


def _make_llm(response_content: str) -> AsyncMock:
    """Return a mock LLMGateway whose generate() returns response_content."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_make_llm_response(response_content))
    return llm


def _make_semantic_extractor(is_duplicate: bool = False) -> MagicMock:
    """Return a mock SemanticExtractor."""
    extractor = MagicMock()
    extractor._is_duplicate = MagicMock(return_value=is_duplicate)
    extractor.default_importance = 0.8
    extractor.memory = MagicMock()
    extractor.memory.add_memory = MagicMock()
    return extractor


def _make_lesson_extractor(is_duplicate: bool = False) -> MagicMock:
    """Return a mock LessonExtractor."""
    extractor = MagicMock()
    extractor._is_duplicate = AsyncMock(return_value=is_duplicate)
    extractor._append_to_file = MagicMock()
    extractor.memory = MagicMock()
    extractor.memory.add_memory = MagicMock()
    return extractor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_stores_facts_and_lessons() -> None:
    """Valid JSON with facts + lessons → both are stored."""
    payload = json.dumps({
        "facts": ["User prefers dark mode", "Project uses Python 3.11"],
        "lessons": [{"title": "Be concise", "context": "Long answer", "lesson": "Keep it short"}],
    })
    llm = _make_llm(payload)
    semantic = _make_semantic_extractor(is_duplicate=False)
    lesson = _make_lesson_extractor(is_duplicate=False)

    extractor = CombinedTurnExtractor(llm=llm, semantic_extractor=semantic, lesson_extractor=lesson)
    result = await extractor.extract_and_store(
        user_message="Hello",
        assistant_response="Hi there",
        session_id="sess-1",
        trace_id="trace-1",
    )

    assert result["facts_stored"] == 2
    assert result["lessons_stored"] == 1
    assert semantic.memory.add_memory.call_count == 2
    assert lesson._append_to_file.call_count == 1
    assert lesson.memory.add_memory.call_count == 1


@pytest.mark.asyncio
async def test_extract_handles_empty_facts() -> None:
    """LLM returns empty facts list → only lessons are stored."""
    payload = json.dumps({
        "facts": [],
        "lessons": [{"title": "Prefer lists", "context": "Long prose", "lesson": "Use bullet points"}],
    })
    llm = _make_llm(payload)
    semantic = _make_semantic_extractor(is_duplicate=False)
    lesson = _make_lesson_extractor(is_duplicate=False)

    extractor = CombinedTurnExtractor(llm=llm, semantic_extractor=semantic, lesson_extractor=lesson)
    result = await extractor.extract_and_store(
        user_message="Show me info",
        assistant_response="Here is a paragraph...",
        session_id="sess-2",
        trace_id="trace-2",
    )

    assert result["facts_stored"] == 0
    assert result["lessons_stored"] == 1
    semantic.memory.add_memory.assert_not_called()
    lesson._append_to_file.assert_called_once()


@pytest.mark.asyncio
async def test_extract_handles_malformed_json() -> None:
    """LLM returns garbage → no crash, returns zero counts."""
    llm = _make_llm("This is not JSON at all!!!")
    semantic = _make_semantic_extractor()
    lesson = _make_lesson_extractor()

    extractor = CombinedTurnExtractor(llm=llm, semantic_extractor=semantic, lesson_extractor=lesson)
    result = await extractor.extract_and_store(
        user_message="Hi",
        assistant_response="Hello",
        session_id="sess-3",
        trace_id="trace-3",
    )

    assert result == {"facts_stored": 0, "lessons_stored": 0}
    semantic.memory.add_memory.assert_not_called()
    lesson._append_to_file.assert_not_called()


@pytest.mark.asyncio
async def test_single_llm_call_per_turn() -> None:
    """extract_and_store must call llm.generate exactly once per turn."""
    payload = json.dumps({"facts": ["Fact A"], "lessons": []})
    llm = _make_llm(payload)
    semantic = _make_semantic_extractor(is_duplicate=False)
    lesson = _make_lesson_extractor()

    extractor = CombinedTurnExtractor(llm=llm, semantic_extractor=semantic, lesson_extractor=lesson)
    await extractor.extract_and_store(
        user_message="What is 2+2?",
        assistant_response="It is 4.",
        session_id="sess-4",
        trace_id="trace-4",
    )

    llm.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Unit tests for _parse_combined_response helper
# ---------------------------------------------------------------------------

def test_parse_combined_response_valid() -> None:
    raw = json.dumps({"facts": ["fact1", "fact2"], "lessons": [{"title": "t", "context": "c", "lesson": "l"}]})
    facts, lessons = _parse_combined_response(raw)
    assert facts == ["fact1", "fact2"]
    assert len(lessons) == 1
    assert lessons[0]["title"] == "t"


def test_parse_combined_response_markdown_fences() -> None:
    raw = '```json\n{"facts": ["x"], "lessons": []}\n```'
    facts, lessons = _parse_combined_response(raw)
    assert facts == ["x"]
    assert lessons == []


def test_parse_combined_response_garbage() -> None:
    facts, lessons = _parse_combined_response("garbage")
    assert facts == []
    assert lessons == []


def test_parse_combined_response_empty_both() -> None:
    raw = json.dumps({"facts": [], "lessons": []})
    facts, lessons = _parse_combined_response(raw)
    assert facts == []
    assert lessons == []
