"""Tests for the OpenAI-compatible /v1/chat/completions endpoint (Gap H5)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.v1_chat import v1_router
from core.agent import Agent


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.include_router(v1_router)
    return _app


@pytest.fixture
def mock_agent() -> Agent:
    agent = MagicMock(spec=Agent)
    agent.process_message = AsyncMock(return_value="Hello from dolOS")
    return agent


class TestV1ChatCompletions:
    def test_basic_completion(self, app: FastAPI, mock_agent: Agent) -> None:
        """Well-formed request returns an OpenAI-shaped response."""
        app.state.agent = mock_agent
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "dolOS",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Hello from dolOS"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert data["id"].startswith("chatcmpl-")

    def test_session_id_from_user_field(self, app: FastAPI, mock_agent: Agent) -> None:
        """When ``user`` is provided it is used as the session_id."""
        app.state.agent = mock_agent
        client = TestClient(app)

        client.post(
            "/v1/chat/completions",
            json={
                "model": "dolOS",
                "messages": [{"role": "user", "content": "hi"}],
                "user": "test-session-abc",
            },
        )

        mock_agent.process_message.assert_called_once_with(
            session_id="test-session-abc", message="hi"
        )

    def test_session_id_generated_when_absent(self, app: FastAPI, mock_agent: Agent) -> None:
        """When ``user`` is omitted a random session_id is generated."""
        app.state.agent = mock_agent
        client = TestClient(app)

        client.post(
            "/v1/chat/completions",
            json={
                "model": "dolOS",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

        call_kwargs = mock_agent.process_message.call_args[1]
        assert len(call_kwargs["session_id"]) == 32  # uuid hex

    def test_last_user_message_extracted(self, app: FastAPI, mock_agent: Agent) -> None:
        """Only the last user message is forwarded to the agent."""
        app.state.agent = mock_agent
        client = TestClient(app)

        client.post(
            "/v1/chat/completions",
            json={
                "model": "dolOS",
                "messages": [
                    {"role": "user", "content": "first message"},
                    {"role": "assistant", "content": "ok"},
                    {"role": "user", "content": "last message"},
                ],
            },
        )

        mock_agent.process_message.assert_called_once_with(
            session_id=mock_agent.process_message.call_args[1]["session_id"],
            message="last message",
        )

    def test_stream_true_returns_501(self, app: FastAPI, mock_agent: Agent) -> None:
        """stream=true returns 501 Not Implemented until SSE is wired up."""
        app.state.agent = mock_agent
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "dolOS",
                "messages": [{"role": "user", "content": "stream me"}],
                "stream": True,
            },
        )

        assert response.status_code == 501

    def test_no_agent_returns_500(self, app: FastAPI) -> None:
        """Missing agent state returns 500."""
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "dolOS",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

        assert response.status_code == 500

    def test_default_model_field(self, app: FastAPI, mock_agent: Agent) -> None:
        """model defaults to 'dolOS' and is echoed in the response."""
        app.state.agent = mock_agent
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

        assert response.status_code == 200
        assert response.json()["model"] == "dolOS"
