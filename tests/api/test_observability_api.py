"""Tests for the observability REST and WebSocket endpoints."""

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.observability import router, set_collector
from core.telemetry import Event, EventType


def test_get_recent_events():
    """GET /events/recent should return events from the collector's buffer."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    mock_collector = MagicMock()
    mock_collector.get_recent_events.return_value = [
        Event(EventType.LLM_CALL_START, "agent", "t1", timestamp=123.45)
    ]
    set_collector(mock_collector)

    response = client.get("/events/recent")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["event_type"] == "llm.call.start"
    assert data[0]["timestamp"] == 123.45


def test_websocket_events_live():
    """WS /events/live should accept connections."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    with client.websocket_connect("/events/live"):
        # We don't necessarily need to send/receive here yet,
        # just verify connection is accepted.
        pass

