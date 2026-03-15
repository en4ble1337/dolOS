from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.chat import chat_router
from core.agent import Agent
from core.telemetry import EventBus, EventType


# We have to provide the app with dependencies attached manually or via state.
@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.include_router(chat_router)
    return _app


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


@pytest.fixture
def mock_agent() -> Agent:
    agent = MagicMock(spec=Agent)
    agent.process_message = AsyncMock(return_value="Assistant API reply")
    return agent


class TestChatAPI:
    def test_post_chat(
        self, app: FastAPI, mock_agent: Agent, mock_event_bus: EventBus
    ) -> None:
        """Test hitting the /chat REST endpoint."""
        app.state.agent = mock_agent
        app.state.event_bus = mock_event_bus

        client = TestClient(app)

        response = client.post(
            "/chat",
            json={"session_id": "api-session", "message": "ping via api"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Assistant API reply"

        # Verify agent was called correctly
        mock_agent.process_message.assert_called_once_with(
            session_id="api-session", message="ping via api"
        )

        # Verify telemetry
        emitted = [
            call.args[0].event_type
            for call in mock_event_bus.emit.await_args_list
        ]
        assert EventType.MESSAGE_RECEIVED in emitted
        assert EventType.MESSAGE_SENT in emitted
