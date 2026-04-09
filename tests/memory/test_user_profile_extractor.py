"""Tests for UserProfileExtractor."""

from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from core.telemetry import EventBus, EventType
from memory.user_profile_extractor import UserProfileExtractor


def _valid_profile(extra_line: str = "") -> str:
    body = textwrap.dedent(
        f"""\
        # User Profile

        ## Communication Style
        - Direct and concise

        ## Technical Profile
        - Works primarily in Python

        ## Current Work Context
        - Implementing Phase E

        ## Interaction Preferences
        - Prefers pragmatic updates

        ## Things to Always Do
        - Write tests first

        ## Things to Never Do
        - Revert unrelated changes
        """
    )
    if not extra_line:
        return body
    return body + f"\n{extra_line}\n"


def _make_recent_turns() -> list[dict]:
    return [
        {"type": "user", "content": "Please add Phase E."},
        {"type": "assistant", "content": "I will add the plan and tests first."},
        {"type": "user", "content": "Use TDD and do not clobber USER.md."},
        {"type": "assistant", "content": "I will keep the update optional and safe."},
    ]


async def _advance_to_threshold(
    extractor: UserProfileExtractor,
    *,
    session_id: str = "sess-1",
    recent_turns: list[dict] | None = None,
    trace_id: str = "trace-1",
    turns: int = UserProfileExtractor.UPDATE_EVERY_N_TURNS,
) -> int:
    recent_turns = recent_turns or _make_recent_turns()
    result = 0
    for _ in range(turns):
        result = await extractor.maybe_update(
            session_id=session_id,
            recent_turns=recent_turns,
            trace_id=trace_id,
        )
    return result


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock()
    return llm


@pytest.fixture
def mock_static_loader() -> MagicMock:
    loader = MagicMock()
    loader.evict_by_source_tag.return_value = 3
    loader.index_file.return_value = 4
    return loader


@pytest.fixture
def profile_tmp_dir() -> Path:
    base_dir = Path(".tmp-tests")
    base_dir.mkdir(exist_ok=True)
    temp_dir = base_dir / f"user-profile-{uuid.uuid4().hex}"
    temp_dir.mkdir()
    yield temp_dir


def _make_llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.content = content
    response.tool_calls = None
    return response


class TestUserProfileExtractor:
    @pytest.mark.asyncio
    async def test_below_threshold_does_not_call_llm(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        profile_path.write_text(_valid_profile(), encoding="utf-8")
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        result = await _advance_to_threshold(
            extractor,
            turns=UserProfileExtractor.UPDATE_EVERY_N_TURNS - 1,
        )

        assert result == 0
        mock_llm.generate.assert_not_called()
        mock_static_loader.evict_by_source_tag.assert_not_called()
        mock_static_loader.index_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_none_is_safe_noop(
        self,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        existing_profile = _valid_profile("Existing marker")
        profile_path.write_text(existing_profile, encoding="utf-8")
        extractor = UserProfileExtractor(
            llm=None,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        result = await _advance_to_threshold(extractor)

        assert result == 0
        assert profile_path.read_text(encoding="utf-8") == existing_profile
        mock_static_loader.evict_by_source_tag.assert_not_called()
        mock_static_loader.index_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_update_writes_user_md_and_reindexes(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        profile_path.write_text(_valid_profile("Old profile marker"), encoding="utf-8")
        new_profile = _valid_profile("Updated profile marker")
        mock_llm.generate.return_value = _make_llm_response(new_profile)
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        result = await _advance_to_threshold(extractor)

        assert result == 1
        assert profile_path.read_text(encoding="utf-8") == new_profile
        mock_static_loader.index_file.assert_called_once_with(
            str(profile_path),
            source_tag="user_profile",
        )

    @pytest.mark.asyncio
    async def test_successful_update_evicts_stale_user_profile_chunks_before_reindex(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        profile_path.write_text(_valid_profile(), encoding="utf-8")
        mock_llm.generate.return_value = _make_llm_response(_valid_profile("New marker"))
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        result = await _advance_to_threshold(extractor)

        assert result == 1
        assert mock_static_loader.method_calls[:2] == [
            call.evict_by_source_tag("user_profile"),
            call.index_file(str(profile_path), source_tag="user_profile"),
        ]

    @pytest.mark.asyncio
    async def test_invalid_llm_output_does_not_clobber_existing_profile(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        existing_profile = _valid_profile("Keep this marker")
        profile_path.write_text(existing_profile, encoding="utf-8")
        mock_llm.generate.return_value = _make_llm_response(
            "## Communication Style\nOnly one section"
        )
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        result = await _advance_to_threshold(extractor)

        assert result == 0
        assert profile_path.read_text(encoding="utf-8") == existing_profile
        mock_static_loader.evict_by_source_tag.assert_not_called()
        mock_static_loader.index_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_exception_does_not_crash(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        existing_profile = _valid_profile("Stable marker")
        profile_path.write_text(existing_profile, encoding="utf-8")
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        result = await _advance_to_threshold(extractor)

        assert result == 0
        assert profile_path.read_text(encoding="utf-8") == existing_profile
        mock_static_loader.evict_by_source_tag.assert_not_called()
        mock_static_loader.index_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_existing_user_md_in_prompt(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        existing_profile = _valid_profile("Existing profile marker")
        profile_path.write_text(existing_profile, encoding="utf-8")
        mock_llm.generate.return_value = _make_llm_response(_valid_profile("Updated marker"))
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        await _advance_to_threshold(extractor)

        prompt = mock_llm.generate.await_args.kwargs["messages"][0]["content"]
        assert "Existing profile marker" in prompt

    @pytest.mark.asyncio
    async def test_recent_turns_are_rendered_into_prompt(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        profile_path.write_text(_valid_profile(), encoding="utf-8")
        mock_llm.generate.return_value = _make_llm_response(_valid_profile("Updated marker"))
        recent_turns = _make_recent_turns()
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        await _advance_to_threshold(extractor, recent_turns=recent_turns)

        prompt = mock_llm.generate.await_args.kwargs["messages"][0]["content"]
        assert "Please add Phase E." in prompt
        assert "I will add the plan and tests first." in prompt
        assert "Use TDD and do not clobber USER.md." in prompt
        assert "I will keep the update optional and safe." in prompt

    @pytest.mark.asyncio
    async def test_emits_start_and_complete_events_on_success(
        self,
        mock_llm: MagicMock,
        mock_static_loader: MagicMock,
        mock_event_bus: EventBus,
        profile_tmp_dir: Path,
    ) -> None:
        profile_path = profile_tmp_dir / "USER.md"
        profile_path.write_text(_valid_profile(), encoding="utf-8")
        mock_llm.generate.return_value = _make_llm_response(_valid_profile("Updated marker"))
        extractor = UserProfileExtractor(
            llm=mock_llm,
            profile_path=str(profile_path),
            static_loader=mock_static_loader,
            event_bus=mock_event_bus,
        )

        await _advance_to_threshold(extractor)

        emitted_types = [call_args.args[0].event_type for call_args in mock_event_bus.emit.await_args_list]
        assert EventType.USER_PROFILE_UPDATE_START in emitted_types
        assert EventType.USER_PROFILE_UPDATE_COMPLETE in emitted_types
