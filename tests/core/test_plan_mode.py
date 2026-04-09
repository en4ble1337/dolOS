"""Tests for Plan Mode (Gap 3).

TDD Red phase — these tests MUST FAIL before:
  - core/plan_mode.py exists
  - core/agent.py accepts plan_mode_state
  - core/commands.py has /plan and /approve handlers
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.plan_mode import PlanModeState


# ---------------------------------------------------------------------------
# PlanModeState — unit tests
# ---------------------------------------------------------------------------

class TestPlanModeStateInit:
    def test_initial_active_is_false(self):
        state = PlanModeState()
        assert state.active is False

    def test_initial_pending_plan_is_empty(self):
        state = PlanModeState()
        assert state.pending_plan == []


class TestPlanModeStateEnter:
    def test_enter_sets_active_true(self):
        state = PlanModeState()
        state.enter()
        assert state.active is True

    def test_enter_clears_pending_plan(self):
        state = PlanModeState()
        state.pending_plan = ["old step 1", "old step 2"]
        state.enter()
        assert state.pending_plan == []

    def test_enter_is_idempotent(self):
        state = PlanModeState()
        state.enter()
        state.store_plan(["step a"])
        state.enter()  # re-enter clears the plan
        assert state.pending_plan == []
        assert state.active is True


class TestPlanModeStateStorePlan:
    def test_store_plan_sets_pending_plan(self):
        state = PlanModeState()
        state.store_plan(["do x", "do y", "do z"])
        assert state.pending_plan == ["do x", "do y", "do z"]

    def test_store_empty_plan(self):
        state = PlanModeState()
        state.store_plan([])
        assert state.pending_plan == []

    def test_store_plan_overwrites_previous(self):
        state = PlanModeState()
        state.store_plan(["step 1"])
        state.store_plan(["step A", "step B"])
        assert state.pending_plan == ["step A", "step B"]


class TestPlanModeStateExit:
    def test_exit_sets_active_false(self):
        state = PlanModeState()
        state.enter()
        state.exit()
        assert state.active is False

    def test_exit_clears_pending_plan(self):
        state = PlanModeState()
        state.enter()
        state.store_plan(["step 1", "step 2"])
        state.exit()
        assert state.pending_plan == []

    def test_exit_when_already_inactive_is_safe(self):
        state = PlanModeState()
        state.exit()  # should not raise
        assert state.active is False


# ---------------------------------------------------------------------------
# Agent integration — plan mode hides tools and stores steps
# ---------------------------------------------------------------------------

def _make_agent_with_plan_mode():
    """Build a minimal Agent with mocked dependencies + PlanModeState."""
    from core.agent import Agent
    from core.plan_mode import PlanModeState

    llm = MagicMock()
    llm.settings = MagicMock()
    llm.settings.primary_model = "test-model"
    llm.settings.model_context_window = 32768
    llm.settings.token_budget_warn_threshold = 0.8
    llm.settings.token_budget_summarize_threshold = 0.7

    memory = MagicMock()
    memory.search.return_value = []
    memory.add_memory.return_value = None

    plan_state = PlanModeState()
    agent = Agent(
        llm=llm,
        memory=memory,
        plan_mode_state=plan_state,
    )
    return agent, plan_state


class TestAgentPlanModeHidesTools:
    @pytest.mark.asyncio
    async def test_plan_mode_active_passes_no_tools_to_llm(self):
        """When plan mode is active, the LLM must receive tools=None."""
        from core.plan_mode import PlanModeState

        agent, plan_state = _make_agent_with_plan_mode()
        plan_state.enter()

        # LLM returns a numbered plan (no tool_calls)
        mock_response = MagicMock()
        mock_response.content = "1. Read the file\n2. Write the output"
        mock_response.tool_calls = []
        mock_response.input_tokens = 10
        mock_response.output_tokens = 20
        agent.llm.generate = AsyncMock(return_value=mock_response)

        with patch("os.path.exists", return_value=False):
            await agent.process_message("sess-1", "Delete all logs")

        call_kwargs = agent.llm.generate.call_args
        assert call_kwargs.kwargs.get("tools") is None or call_kwargs[1].get("tools") is None


class TestAgentPlanModeStoresSteps:
    @pytest.mark.asyncio
    async def test_numbered_steps_stored_in_pending_plan(self):
        """Numbered steps in LLM response are parsed and stored."""
        agent, plan_state = _make_agent_with_plan_mode()
        plan_state.enter()

        mock_response = MagicMock()
        mock_response.content = "1. Read the config\n2. Validate schema\n3. Apply changes"
        mock_response.tool_calls = []
        mock_response.input_tokens = 10
        mock_response.output_tokens = 20
        agent.llm.generate = AsyncMock(return_value=mock_response)

        with patch("os.path.exists", return_value=False):
            await agent.process_message("sess-2", "Update config")

        assert plan_state.pending_plan == [
            "Read the config",
            "Validate schema",
            "Apply changes",
        ]

    @pytest.mark.asyncio
    async def test_no_steps_stored_when_not_in_plan_mode(self):
        """Outside plan mode, pending_plan stays empty."""
        agent, plan_state = _make_agent_with_plan_mode()
        # plan mode NOT entered

        mock_response = MagicMock()
        mock_response.content = "1. Step A\n2. Step B"
        mock_response.tool_calls = []
        mock_response.input_tokens = 10
        mock_response.output_tokens = 20
        agent.llm.generate = AsyncMock(return_value=mock_response)

        with patch("os.path.exists", return_value=False):
            await agent.process_message("sess-3", "Do something")

        assert plan_state.pending_plan == []


# ---------------------------------------------------------------------------
# CommandRouter — /plan and /approve commands
# ---------------------------------------------------------------------------

def _make_command_router(plan_state: PlanModeState | None = None):
    """Build a CommandRouter with a minimal Agent stub."""
    from core.commands import CommandRouter

    agent = MagicMock()
    agent.plan_mode_state = plan_state
    agent.summarizer = None

    memory = MagicMock()
    memory.search.return_value = []

    router = CommandRouter(agent=agent, memory=memory)
    return router, agent


class TestCmdPlan:
    @pytest.mark.asyncio
    async def test_plan_enters_plan_mode(self):
        state = PlanModeState()
        router, agent = _make_command_router(plan_state=state)
        result = await router.handle("sess", "/plan")
        assert result is not None
        assert state.active is True

    @pytest.mark.asyncio
    async def test_plan_returns_confirmation_message(self):
        state = PlanModeState()
        router, _ = _make_command_router(plan_state=state)
        result = await router.handle("sess", "/plan")
        assert result is not None
        assert "plan" in result.lower() or "mode" in result.lower()

    @pytest.mark.asyncio
    async def test_plan_without_state_returns_error(self):
        router, _ = _make_command_router(plan_state=None)
        result = await router.handle("sess", "/plan")
        assert result is not None
        assert "not configured" in result.lower() or "error" in result.lower()


class TestCmdApprove:
    @pytest.mark.asyncio
    async def test_approve_without_active_plan_mode_returns_error(self):
        state = PlanModeState()  # NOT entered
        router, _ = _make_command_router(plan_state=state)
        result = await router.handle("sess", "/approve")
        assert result is not None
        assert "not in plan mode" in result.lower() or "plan" in result.lower()

    @pytest.mark.asyncio
    async def test_approve_with_no_pending_plan_returns_error(self):
        state = PlanModeState()
        state.enter()  # active but no plan stored
        router, _ = _make_command_router(plan_state=state)
        result = await router.handle("sess", "/approve")
        assert result is not None
        assert "no pending plan" in result.lower() or "pending" in result.lower()

    @pytest.mark.asyncio
    async def test_approve_calls_process_message_per_step(self):
        state = PlanModeState()
        state.enter()
        state.store_plan(["Read the file", "Write the output"])

        router, agent = _make_command_router(plan_state=state)
        agent.process_message = AsyncMock(return_value="done")

        result = await router.handle("sess", "/approve")

        assert agent.process_message.call_count == 2
        assert result is not None

    @pytest.mark.asyncio
    async def test_approve_exits_plan_mode(self):
        state = PlanModeState()
        state.enter()
        state.store_plan(["Step 1"])

        router, agent = _make_command_router(plan_state=state)
        agent.process_message = AsyncMock(return_value="result")

        await router.handle("sess", "/approve")
        assert state.active is False

    @pytest.mark.asyncio
    async def test_approve_without_state_returns_error(self):
        router, _ = _make_command_router(plan_state=None)
        result = await router.handle("sess", "/approve")
        assert result is not None
        assert "not configured" in result.lower() or "error" in result.lower()
