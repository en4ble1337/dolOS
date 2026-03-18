"""Tests for memory, skills, and telemetry API routes."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.memory import router as memory_router
from api.routes.skills import router as skills_router
from api.routes.telemetry import router as telemetry_router
from core.telemetry import Event, EventBus, EventType


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


# --- Memory Routes ---


class TestMemoryRoutes:
    @pytest.fixture
    def app(self) -> FastAPI:
        _app = FastAPI()
        _app.include_router(memory_router)
        return _app

    def test_search_no_memory_manager(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/memory/search?q=test")
        assert response.status_code == 503

    def test_search_empty_query(self, app: FastAPI) -> None:
        mock_memory = MagicMock()
        app.state.memory = mock_memory

        client = TestClient(app)
        response = client.get("/memory/search?q=")
        assert response.status_code == 400

    def test_search_returns_results(self, app: FastAPI) -> None:
        mock_memory = MagicMock()
        mock_memory.search.return_value = [
            {
                "text": "test memory",
                "score": 0.95,
                "timestamp": 1710500000.0,
                "importance": 0.8,
                "similarity": 0.9,
                "metadata": {"session_id": "s1"},
            }
        ]
        app.state.memory = mock_memory

        client = TestClient(app)
        response = client.get("/memory/search?q=test&limit=3")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["text"] == "test memory"
        mock_memory.search.assert_called_once_with(query="test", memory_type="episodic", limit=3)

    def test_stats_no_memory_manager(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/memory/stats")
        assert response.status_code == 503


# --- Skills Routes ---


class TestSkillsRoutes:
    @pytest.fixture
    def app(self) -> FastAPI:
        _app = FastAPI()
        _app.include_router(skills_router)
        return _app

    def test_list_skills_no_executor(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/skills")
        assert response.status_code == 503

    def test_list_skills(self, app: FastAPI) -> None:
        mock_executor = MagicMock()
        mock_executor.registry.get_all_skill_names.return_value = ["echo", "read_file"]
        mock_executor.registry.get_schema.side_effect = lambda name: {
            "name": name,
            "description": f"The {name} skill",
            "parameters": {},
        }
        app.state.skill_executor = mock_executor

        client = TestClient(app)
        response = client.get("/skills")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert data["skills"][0]["name"] == "echo"

    def test_invoke_skill_not_found(self, app: FastAPI) -> None:
        mock_executor = MagicMock()
        mock_executor.registry.get_skill.side_effect = KeyError("nope")
        app.state.skill_executor = mock_executor

        client = TestClient(app)
        response = client.post("/skills/nope/invoke", json={"arguments": {}})
        assert response.status_code == 404

    def test_invoke_skill_success(self, app: FastAPI) -> None:
        mock_executor = MagicMock()
        mock_executor.registry.get_skill.return_value = lambda: None  # exists
        mock_executor.execute = AsyncMock(return_value="hello world")
        app.state.skill_executor = mock_executor

        client = TestClient(app)
        response = client.post(
            "/skills/echo/invoke",
            json={"arguments": {"message": "hello"}, "trace_id": "t-1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"] == "hello world"
        assert data["success"] is True


# --- Telemetry Routes ---


class TestTelemetryRoutes:
    @pytest.fixture
    def app(self) -> FastAPI:
        _app = FastAPI()
        _app.include_router(telemetry_router)
        return _app

    def test_events_no_collector(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/telemetry/events")
        assert response.status_code == 503

    def test_events_returns_from_buffer(self, app: FastAPI) -> None:
        mock_collector = MagicMock()
        mock_collector.get_recent_events.return_value = [
            Event(
                event_type=EventType.LLM_CALL_END,
                component="agent.llm",
                trace_id="trace-1",
                payload={"model": "test"},
                duration_ms=100.0,
                success=True,
                timestamp=1710500000.0,
            )
        ]
        app.state.collector = mock_collector

        client = TestClient(app)
        response = client.get("/telemetry/events")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["events"][0]["component"] == "agent.llm"

    def test_events_filter_by_type(self, app: FastAPI) -> None:
        mock_collector = MagicMock()
        mock_collector.get_recent_events.return_value = [
            Event(
                event_type=EventType.LLM_CALL_END,
                component="agent.llm",
                trace_id="t1",
                timestamp=1.0,
            ),
            Event(
                event_type=EventType.MEMORY_HIT,
                component="memory",
                trace_id="t2",
                timestamp=2.0,
            ),
        ]
        app.state.collector = mock_collector

        client = TestClient(app)
        response = client.get("/telemetry/events?event_type=memory.hit")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["events"][0]["event_type"] == "memory.hit"

    def test_trace_not_found(self, app: FastAPI) -> None:
        mock_collector = MagicMock()
        mock_db = MagicMock()

        # Mock the trace query returning None
        trace_cursor = MagicMock()
        trace_cursor.fetchone = AsyncMock(return_value=None)

        # Mock the events query returning empty
        event_cursor = MagicMock()
        event_cursor.fetchall = AsyncMock(return_value=[])

        mock_db.execute = AsyncMock(side_effect=[trace_cursor, event_cursor])
        mock_collector._db = mock_db
        app.state.collector = mock_collector

        client = TestClient(app)
        response = client.get("/telemetry/traces/nonexistent")

        assert response.status_code == 404
