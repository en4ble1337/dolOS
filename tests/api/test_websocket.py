"""Tests for the WebSocket ConnectionManager."""

from unittest.mock import AsyncMock

import pytest

from api.websocket import ConnectionManager


@pytest.mark.asyncio
async def test_manager_accepts_connection():
    """Manager should store the websocket connection."""
    manager = ConnectionManager()
    ws = AsyncMock()
    await manager.connect(ws)
    assert ws in manager.active_connections


@pytest.mark.asyncio
async def test_manager_removes_connection():
    """Manager should remove the websocket on disconnect."""
    manager = ConnectionManager()
    ws = AsyncMock()
    await manager.connect(ws)
    manager.disconnect(ws)
    assert ws not in manager.active_connections


@pytest.mark.asyncio
async def test_manager_broadcasts_to_all():
    """Manager should send a message to all connected clients."""
    manager = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    await manager.connect(ws1)
    await manager.connect(ws2)

    message = {"event": "test"}
    await manager.broadcast(message)

    ws1.send_json.assert_called_with(message)
    ws2.send_json.assert_called_with(message)
