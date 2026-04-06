"""Tests for core/commands.py (Gap 10)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_router():
    """Build a CommandRouter with fully mocked dependencies."""
    from core.commands import CommandRouter

    agent = MagicMock()
    agent.summarizer = None
    agent.skill_executor = MagicMock()
    agent.skill_executor.registry.get_all_skill_names.return_value = [
        "run_command", "read_file", "write_file"
    ]
    agent.skill_executor.registry.get_schema.side_effect = lambda name: {
        "name": name,
        "description": f"Does {name} stuff.",
    }
    agent.llm = MagicMock()
    agent.memory = MagicMock()
    agent.event_bus = None
    agent.combined_extractor = None
    agent.lesson_extractor = None
    agent.semantic_extractor = None

    memory = MagicMock()
    memory.search.return_value = [
        {"score": 0.9, "text": "User asked about Python last week."}
    ]
    memory.vector_store = MagicMock()
    memory.vector_store.count.return_value = 42

    return CommandRouter(agent=agent, memory=memory)


class TestNotACommand:
    @pytest.mark.asyncio
    async def test_plain_text_returns_none(self):
        router = _make_router()
        result = await router.handle("s1", "hello world")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(self):
        router = _make_router()
        result = await router.handle("s1", "")
        assert result is None


class TestSkillsCommand:
    @pytest.mark.asyncio
    async def test_skills_list_returns_names(self):
        router = _make_router()
        result = await router.handle("s1", "/skills list")
        assert result is not None
        assert "run_command" in result
        assert "read_file" in result

    @pytest.mark.asyncio
    async def test_skills_bare_also_works(self):
        router = _make_router()
        result = await router.handle("s1", "/skills")
        assert result is not None
        assert "run_command" in result

    @pytest.mark.asyncio
    async def test_no_llm_call(self):
        """Skills list must not invoke the agent's LLM."""
        router = _make_router()
        await router.handle("s1", "/skills list")
        router.agent.llm.generate.assert_not_called()


class TestMemoryCommands:
    @pytest.mark.asyncio
    async def test_memory_search_returns_results(self):
        router = _make_router()
        result = await router.handle("s1", "/memory search Python")
        assert result is not None
        assert "Python" in result

    @pytest.mark.asyncio
    async def test_memory_search_no_args(self):
        router = _make_router()
        result = await router.handle("s1", "/memory search")
        assert result is not None
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_memory_stats(self):
        router = _make_router()
        result = await router.handle("s1", "/memory stats")
        assert result is not None
        assert "42" in result


class TestDoctorCommand:
    @pytest.mark.asyncio
    async def test_doctor_returns_health(self):
        router = _make_router()
        result = await router.handle("s1", "/doctor")
        assert result is not None
        assert "LLM gateway" in result

    @pytest.mark.asyncio
    async def test_doctor_reports_missing_optional(self):
        router = _make_router()
        router.agent.summarizer = None
        result = await router.handle("s1", "/doctor")
        assert "Summarizer" in result


class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_lists_commands(self):
        router = _make_router()
        result = await router.handle("s1", "/help")
        assert result is not None
        assert "/memory search" in result
        assert "/skills" in result
        assert "/doctor" in result


class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_unknown_returns_error_message(self):
        router = _make_router()
        result = await router.handle("s1", "/foobar")
        assert result is not None
        assert "Unknown command" in result


class TestCaseSensitivity:
    @pytest.mark.asyncio
    async def test_command_case_insensitive(self):
        router = _make_router()
        result = await router.handle("s1", "/SKILLS LIST")
        assert result is not None
        assert "run_command" in result
