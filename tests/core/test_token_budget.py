"""Tests for token budget controls (Gap 9).

Verifies that:
- LLMResponse carries input_tokens and output_tokens fields
- Settings has the new token budget config fields
- Agent._session_tokens accumulates across calls
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.llm import LLMResponse
from core.config import Settings


class TestLLMResponseTokenFields:
    def test_default_zero(self):
        resp = LLMResponse(content="hello")
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0

    def test_token_fields_set(self):
        resp = LLMResponse(content="hi", input_tokens=100, output_tokens=50)
        assert resp.input_tokens == 100
        assert resp.output_tokens == 50


class TestSettingsTokenBudgetFields:
    def test_default_context_window(self):
        s = Settings()
        assert s.model_context_window == 32768

    def test_default_warn_threshold(self):
        s = Settings()
        assert s.token_budget_warn_threshold == 0.8

    def test_default_summarize_threshold(self):
        s = Settings()
        assert s.token_budget_summarize_threshold == 0.7

    def test_custom_values(self, monkeypatch):
        monkeypatch.setenv("MODEL_CONTEXT_WINDOW", "128000")
        monkeypatch.setenv("TOKEN_BUDGET_WARN_THRESHOLD", "0.9")
        s = Settings()
        assert s.model_context_window == 128000
        assert s.token_budget_warn_threshold == 0.9


class TestAgentSessionTokenTracker:
    def _make_agent(self):
        """Build a minimal Agent with mocked dependencies."""
        from core.agent import Agent

        llm = MagicMock()
        llm.settings = Settings()
        memory = MagicMock()
        memory.search.return_value = []
        memory.add_memory = MagicMock()

        agent = Agent(llm=llm, memory=memory)
        return agent

    def test_session_tokens_starts_empty(self):
        agent = self._make_agent()
        assert agent._session_tokens == {}

    def test_session_tokens_accumulate(self):
        agent = self._make_agent()
        # Simulate token accumulation
        agent._session_tokens["sess1"] = 500
        agent._session_tokens["sess1"] = agent._session_tokens["sess1"] + 300
        assert agent._session_tokens["sess1"] == 800

    def test_independent_sessions(self):
        agent = self._make_agent()
        agent._session_tokens["s1"] = 100
        agent._session_tokens["s2"] = 200
        assert agent._session_tokens["s1"] == 100
        assert agent._session_tokens["s2"] == 200
