"""Tests for spawn_subagent skill (Gap 6).

TDD Red phase — these tests MUST FAIL before skills/local/subagent.py exists.

Design: spawn_subagent creates a scoped Agent with PermissionPolicy(allow_only=tools).
Tests verify isolation (tools param restricts LLM-visible schemas) and basic behaviour.
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_llm(response_text: str = "done") -> MagicMock:
    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.primary_model = "test-model"
    llm.settings.model_context_window = 32768
    llm.settings.token_budget_warn_threshold = 0.8
    llm.settings.token_budget_summarize_threshold = 0.7

    mock_response = MagicMock()
    mock_response.content = response_text
    mock_response.tool_calls = []
    mock_response.input_tokens = 10
    mock_response.output_tokens = 5
    llm.generate = AsyncMock(return_value=mock_response)
    return llm


def _make_mock_memory() -> MagicMock:
    memory = MagicMock()
    memory.search.return_value = []
    memory.add_memory.return_value = None
    return memory


# ---------------------------------------------------------------------------
# Module-level dependency injection
# ---------------------------------------------------------------------------

class TestSubagentDependencyInjection:
    def test_spawn_without_deps_returns_error(self):
        """spawn_subagent before set_subagent_dependencies returns an error string."""
        import importlib
        import skills.local.subagent as subagent_mod

        # Reset deps by reimporting
        subagent_mod._llm = None
        subagent_mod._memory = None
        subagent_mod._skill_executor = None

        result = asyncio.get_event_loop().run_until_complete(
            subagent_mod.spawn_subagent("do stuff", ["read_file"])
        )
        assert "error" in result.lower() or "not configured" in result.lower()

    def test_set_subagent_dependencies_stores_refs(self):
        import skills.local.subagent as subagent_mod

        llm = MagicMock()
        memory = MagicMock()
        executor = MagicMock()
        subagent_mod.set_subagent_dependencies(llm, memory, executor)

        assert subagent_mod._llm is llm
        assert subagent_mod._memory is memory
        assert subagent_mod._skill_executor is executor


# ---------------------------------------------------------------------------
# Isolation — allow_only restricts schemas visible to sub-agent LLM
# ---------------------------------------------------------------------------

class TestSubagentToolIsolation:
    @pytest.mark.asyncio
    async def test_subagent_allow_only_blocks_run_command(self):
        """Subagent with allow_only={'read_file'} must NOT pass run_command schema to LLM."""
        import skills.local.subagent as subagent_mod

        # Build a registry with both skills
        reg = SkillRegistry()
        reg.register("read_file", "Read a file", lambda path: "content", is_read_only=True)
        reg.register("run_command", "Run a command", lambda cmd: "output", is_read_only=False)

        executor = MagicMock()
        executor.registry = reg

        llm = _make_mock_llm("File content: hello")
        memory = _make_mock_memory()

        subagent_mod.set_subagent_dependencies(llm, memory, executor)

        with patch("os.path.exists", return_value=False):
            await subagent_mod.spawn_subagent("read something", ["read_file"])

        # LLM was called — check the tools argument
        call_kwargs = llm.generate.call_args
        tools_passed = call_kwargs.kwargs.get("tools") or (call_kwargs[1].get("tools") if call_kwargs[1] else None)

        # If tools were passed, run_command must not be among them
        if tools_passed:
            tool_names = [t["function"]["name"] for t in tools_passed]
            assert "run_command" not in tool_names

    @pytest.mark.asyncio
    async def test_subagent_allow_only_includes_allowed_tool(self):
        """Subagent with allow_only={'read_file'} CAN include read_file schema."""
        import skills.local.subagent as subagent_mod

        reg = SkillRegistry()
        reg.register("read_file", "Read a file", lambda path: "content", is_read_only=True)
        reg.register("run_command", "Run cmd", lambda cmd: "out", is_read_only=False)

        executor = MagicMock()
        executor.registry = reg

        llm = _make_mock_llm("Content read.")
        memory = _make_mock_memory()

        subagent_mod.set_subagent_dependencies(llm, memory, executor)

        with patch("os.path.exists", return_value=False):
            await subagent_mod.spawn_subagent("read file", ["read_file"])

        call_kwargs = llm.generate.call_args
        tools_passed = call_kwargs.kwargs.get("tools") or (call_kwargs[1].get("tools") if call_kwargs[1] else None)

        if tools_passed:
            tool_names = [t["function"]["name"] for t in tools_passed]
            assert "read_file" in tool_names


# ---------------------------------------------------------------------------
# Happy path — result returned
# ---------------------------------------------------------------------------

class TestSubagentResult:
    @pytest.mark.asyncio
    async def test_spawn_returns_llm_response(self):
        import skills.local.subagent as subagent_mod

        reg = SkillRegistry()
        executor = MagicMock()
        executor.registry = reg

        llm = _make_mock_llm("Task completed successfully.")
        memory = _make_mock_memory()

        subagent_mod.set_subagent_dependencies(llm, memory, executor)

        with patch("os.path.exists", return_value=False):
            result = await subagent_mod.spawn_subagent("do task", [])

        assert result == "Task completed successfully."

    @pytest.mark.asyncio
    async def test_spawn_emits_subagent_log(self, caplog):
        """[SUBAGENT] log entry must be emitted during spawn."""
        import skills.local.subagent as subagent_mod

        reg = SkillRegistry()
        executor = MagicMock()
        executor.registry = reg

        llm = _make_mock_llm("done")
        memory = _make_mock_memory()

        subagent_mod.set_subagent_dependencies(llm, memory, executor)

        with caplog.at_level(logging.INFO, logger="skills.local.subagent"):
            with patch("os.path.exists", return_value=False):
                await subagent_mod.spawn_subagent("log test", [])

        assert any("[SUBAGENT]" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Skill registration
# ---------------------------------------------------------------------------

class TestSubagentSkillRegistration:
    def test_spawn_subagent_is_registered_in_default_registry(self):
        """spawn_subagent should be importable and register itself."""
        import skills.local.subagent  # noqa: F401 — side-effect: registers skill
        from skills.registry import _default_registry
        names = _default_registry.get_all_skill_names()
        assert "spawn_subagent" in names
