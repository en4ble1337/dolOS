"""Tests for Phase B automatic skill extraction."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.skill_extractor import SkillExtractionTask
from skills.registry import SkillRegistry


def _make_llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.content = content
    return response


def _make_llm(content: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_make_llm_response(content))
    return llm


class _Embedder:
    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self._mapping = mapping

    def encode(self, text: str) -> list[float]:
        return list(self._mapping[text])


@pytest.mark.asyncio
async def test_below_min_tool_calls_does_not_fire() -> None:
    llm = AsyncMock()
    registry = SkillRegistry()
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    result = await extractor.evaluate_and_extract(
        session_id="session-1",
        user_message="Do a thing",
        assistant_response="Done",
        tool_calls_made=["read_file", "write_file"],
        trace_id="trace-1",
    )

    assert result == 0
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_llm_returns_should_create_false() -> None:
    llm = _make_llm(json.dumps({"should_create": False, "reason": "Not reusable"}))
    registry = SkillRegistry()
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    with patch("memory.skill_extractor.create_skill", new=AsyncMock()) as create_skill:
        result = await extractor.evaluate_and_extract(
            session_id="session-1",
            user_message="Do a thing",
            assistant_response="Done",
            tool_calls_made=["a", "b", "c"],
            trace_id="trace-1",
        )

    assert result == 0
    create_skill.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_extraction_calls_create_skill() -> None:
    llm = _make_llm(json.dumps({
        "should_create": True,
        "reason": "Reusable multi-step workflow",
        "name": "reuse_this_pattern",
        "description": "Combine several tools to complete a workflow.",
        "code": "async def handler(**kwargs):\n    return 'ok'",
        "is_read_only": False,
        "concurrency_safe": False,
    }))
    registry = SkillRegistry()
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    with patch("memory.skill_extractor.create_skill", new=AsyncMock(return_value="created")) as create_skill:
        result = await extractor.evaluate_and_extract(
            session_id="session-1",
            user_message="Do a thing",
            assistant_response="Done",
            tool_calls_made=["a", "b", "c"],
            trace_id="trace-1",
        )

    assert result == 1
    create_skill.assert_awaited_once_with(
        "reuse_this_pattern",
        "Combine several tools to complete a workflow.",
        "async def handler(**kwargs):\n    return 'ok'",
        False,
        False,
    )


@pytest.mark.asyncio
async def test_duplicate_skill_skipped() -> None:
    description = "Combine several tools to complete a workflow."
    llm = _make_llm(json.dumps({
        "should_create": True,
        "reason": "Reusable multi-step workflow",
        "name": "reuse_this_pattern",
        "description": description,
        "code": "async def handler(**kwargs):\n    return 'ok'",
        "is_read_only": False,
        "concurrency_safe": False,
    }))
    registry = SkillRegistry()
    registry.set_embedder(_Embedder({description: [1.0, 0.0, 0.0]}))
    registry.register(
        "existing_skill",
        description,
        lambda **kwargs: "",
    )
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    with patch("memory.skill_extractor.create_skill", new=AsyncMock()) as create_skill:
        result = await extractor.evaluate_and_extract(
            session_id="session-1",
            user_message="Do a thing",
            assistant_response="Done",
            tool_calls_made=["a", "b", "c"],
            trace_id="trace-1",
        )

    assert result == 0
    create_skill.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_failure_doesnt_crash() -> None:
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("boom"))
    registry = SkillRegistry()
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    with patch("memory.skill_extractor.create_skill", new=AsyncMock()) as create_skill:
        result = await extractor.evaluate_and_extract(
            session_id="session-1",
            user_message="Do a thing",
            assistant_response="Done",
            tool_calls_made=["a", "b", "c"],
            trace_id="trace-1",
        )

    assert result == 0
    create_skill.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_returns_invalid_json() -> None:
    llm = _make_llm("not valid json")
    registry = SkillRegistry()
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    with patch("memory.skill_extractor.create_skill", new=AsyncMock()) as create_skill:
        result = await extractor.evaluate_and_extract(
            session_id="session-1",
            user_message="Do a thing",
            assistant_response="Done",
            tool_calls_made=["a", "b", "c"],
            trace_id="trace-1",
        )

    assert result == 0
    create_skill.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_skill_failure_doesnt_crash() -> None:
    llm = _make_llm(json.dumps({
        "should_create": True,
        "reason": "Reusable multi-step workflow",
        "name": "failing_pattern",
        "description": "Combine several tools to complete a workflow.",
        "code": "async def handler(**kwargs):\n    return 'ok'",
        "is_read_only": False,
        "concurrency_safe": False,
    }))
    registry = SkillRegistry()
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    with patch("memory.skill_extractor.create_skill", new=AsyncMock(side_effect=RuntimeError("boom"))) as create_skill:
        result = await extractor.evaluate_and_extract(
            session_id="session-1",
            user_message="Do a thing",
            assistant_response="Done",
            tool_calls_made=["a", "b", "c"],
            trace_id="trace-1",
        )

    assert result == 0
    create_skill.assert_awaited_once()


@pytest.mark.asyncio
async def test_is_read_only_and_concurrency_safe_passed_through() -> None:
    llm = _make_llm(json.dumps({
        "should_create": True,
        "reason": "Reusable multi-step workflow",
        "name": "read_only_pattern",
        "description": "Inspect several sources and summarize them.",
        "code": "async def handler(**kwargs):\n    return 'ok'",
        "is_read_only": True,
        "concurrency_safe": True,
    }))
    registry = SkillRegistry()
    extractor = SkillExtractionTask(llm=llm, registry=registry)

    with patch("memory.skill_extractor.create_skill", new=AsyncMock(return_value="created")) as create_skill:
        result = await extractor.evaluate_and_extract(
            session_id="session-1",
            user_message="Do a thing",
            assistant_response="Done",
            tool_calls_made=["a", "b", "c"],
            trace_id="trace-1",
        )

    assert result == 1
    create_skill.assert_awaited_once_with(
        "read_only_pattern",
        "Inspect several sources and summarize them.",
        "async def handler(**kwargs):\n    return 'ok'",
        True,
        True,
    )
