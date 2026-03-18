"""Tests for health check API routes."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.health import router as health_router


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.include_router(health_router)
    return _app


class TestHealthRoutes:
    def test_basic_health(self, app: FastAPI) -> None:
        """Basic liveness check always returns 200."""
        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_deep_health_no_deps(self, app: FastAPI) -> None:
        """Deep health with no dependencies configured returns degraded/unhealthy."""
        client = TestClient(app)
        response = client.get("/health/deep")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("degraded", "unhealthy")
        assert len(data["components"]) == 4

    def test_deep_health_with_collector(self, app: FastAPI) -> None:
        """Deep health with a mock collector that has an active DB."""
        mock_collector = MagicMock()
        mock_collector._db = MagicMock()
        mock_collector._db.execute = AsyncMock(return_value=None)
        app.state.collector = mock_collector

        client = TestClient(app)
        response = client.get("/health/deep")

        assert response.status_code == 200
        data = response.json()
        sqlite_status = next(c for c in data["components"] if c["name"] == "sqlite")
        assert sqlite_status["status"] == "healthy"

    def test_deep_health_includes_heartbeat_component(self, app: FastAPI) -> None:
        """Deep health response always includes a heartbeat component."""
        client = TestClient(app)
        response = client.get("/health/deep")

        data = response.json()
        names = [c["name"] for c in data["components"]]
        assert "heartbeat" in names

    def test_heartbeat_healthy_when_scheduler_running(self, app: FastAPI) -> None:
        """Heartbeat component is healthy when scheduler is running and 0 restart attempts."""
        mock_heartbeat = MagicMock()
        mock_heartbeat.is_running.return_value = True

        mock_switch = MagicMock()
        mock_switch.last_ping_elapsed = 5.0
        mock_switch.restart_attempts = 0
        mock_switch.max_restart_attempts = 3

        app.state.heartbeat = mock_heartbeat
        app.state.dead_man_switch = mock_switch

        client = TestClient(app)
        response = client.get("/health/deep")

        data = response.json()
        hb = next(c for c in data["components"] if c["name"] == "heartbeat")
        assert hb["status"] == "healthy"

    def test_heartbeat_degraded_when_restarts_in_progress(self, app: FastAPI) -> None:
        """Heartbeat is degraded when restart attempts > 0 and < max."""
        mock_heartbeat = MagicMock()
        mock_heartbeat.is_running.return_value = True

        mock_switch = MagicMock()
        mock_switch.last_ping_elapsed = 60.0
        mock_switch.restart_attempts = 1
        mock_switch.max_restart_attempts = 3

        app.state.heartbeat = mock_heartbeat
        app.state.dead_man_switch = mock_switch

        client = TestClient(app)
        response = client.get("/health/deep")

        data = response.json()
        hb = next(c for c in data["components"] if c["name"] == "heartbeat")
        assert hb["status"] == "degraded"

    def test_heartbeat_unhealthy_when_max_restarts_reached(self, app: FastAPI) -> None:
        """Heartbeat is unhealthy when restart attempts == max."""
        mock_heartbeat = MagicMock()
        mock_heartbeat.is_running.return_value = True

        mock_switch = MagicMock()
        mock_switch.last_ping_elapsed = 300.0
        mock_switch.restart_attempts = 3
        mock_switch.max_restart_attempts = 3

        app.state.heartbeat = mock_heartbeat
        app.state.dead_man_switch = mock_switch

        client = TestClient(app)
        response = client.get("/health/deep")

        data = response.json()
        hb = next(c for c in data["components"] if c["name"] == "heartbeat")
        assert hb["status"] == "unhealthy"
