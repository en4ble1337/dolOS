"""WebSocket connection manager for real-time telemetry streaming."""

from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections for event broadcasting."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the active list."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Any) -> None:
        """Send a message to all active WebSocket connections."""
        # Use asyncio.gather to send to all concurrently
        # We need to handle potential disconnections during broadcast
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)
