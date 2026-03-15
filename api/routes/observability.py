"""FastAPI routes for the observability layer (REST + WebSocket)."""

from typing import List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.websocket import ConnectionManager
from core.telemetry import Event, EventCollector

router = APIRouter()
manager = ConnectionManager()
_collector: EventCollector | None = None


# For testing / global initialization
def set_collector(collector: EventCollector):
    global _collector
    _collector = collector
    if _collector:
        _collector.add_callback(broadcast_event)


async def broadcast_event(event: Event):
    """Callback to broadcast new events to all connected WebSocket clients."""
    await manager.broadcast(
        {
            "event_type": (
                event.event_type.value
                if hasattr(event.event_type, "value")
                else str(event.event_type)
            ),
            "component": event.component,
            "trace_id": event.trace_id,
            "payload": event.payload,
            "duration_ms": event.duration_ms,
            "success": event.success,
            "timestamp": event.timestamp,
        }
    )


class EventResponse(BaseModel):
    """Event representation for REST responses."""

    event_type: str
    component: str
    trace_id: str
    payload: dict
    duration_ms: float
    success: bool
    timestamp: float


@router.get("/events/recent", response_model=List[EventResponse])
async def get_recent_events(limit: int = 100):
    """Return the last 'limit' events from the in-memory ring buffer."""
    if _collector is None:
        return []

    events = _collector.get_recent_events(limit)
    return [
        EventResponse(
            event_type=e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
            component=e.component,
            trace_id=e.trace_id,
            payload=e.payload,
            duration_ms=e.duration_ms,
            success=e.success,
            timestamp=e.timestamp,
        )
        for e in events
    ]


@router.websocket("/events/live")
async def websocket_events_live(websocket: WebSocket):
    """Stream live events to the connected client."""
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect messages FROM the client,
            # but we need to keep the connection open and handle disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
