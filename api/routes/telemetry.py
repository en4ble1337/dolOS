"""Telemetry routes for querying events, metrics, and traces."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["telemetry"])


class EventItem(BaseModel):
    """Single telemetry event."""
    event_type: str
    component: str
    trace_id: str
    payload: dict[str, Any]
    duration_ms: float
    success: bool
    timestamp: float


class EventsResponse(BaseModel):
    """Response for event queries."""
    events: list[EventItem]
    count: int


class MetricItem(BaseModel):
    """Single aggregated metric."""
    timestamp: float
    metric_name: str
    value: float
    labels: dict[str, Any]


class MetricsResponse(BaseModel):
    """Response for metrics queries."""
    metrics: list[MetricItem]
    count: int


class TraceDetail(BaseModel):
    """Full trace detail with associated events."""
    trace_id: str
    started_at: float
    completed_at: float | None
    channel: str | None
    model_used: str | None
    total_tokens: int
    memory_hits: int
    tools_invoked: list[str]
    success: bool
    events: list[EventItem]


def _get_collector(request: Request):
    collector = getattr(request.app.state, "collector", None)
    if collector is None:
        raise HTTPException(status_code=503, detail="EventCollector not configured")
    return collector


@router.get("/telemetry/events", response_model=EventsResponse)
async def get_events(
    request: Request,
    event_type: str | None = None,
    component: str | None = None,
    limit: int = 100,
) -> EventsResponse:
    """Return recent telemetry events with optional filters."""
    collector = _get_collector(request)

    # Get from ring buffer for speed
    events = collector.get_recent_events(limit * 2)  # over-fetch for filtering

    items: list[EventItem] = []
    for e in events:
        etype = e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)

        if event_type and etype != event_type:
            continue
        if component and e.component != component:
            continue

        items.append(EventItem(
            event_type=etype,
            component=e.component,
            trace_id=e.trace_id,
            payload=e.payload,
            duration_ms=e.duration_ms,
            success=e.success,
            timestamp=e.timestamp,
        ))

        if len(items) >= limit:
            break

    return EventsResponse(events=items, count=len(items))


@router.get("/telemetry/metrics", response_model=MetricsResponse)
async def get_metrics(
    request: Request,
    limit: int = 100,
) -> MetricsResponse:
    """Return the most recent aggregated metrics."""
    collector = _get_collector(request)

    if collector._db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    cursor = await collector._db.execute(
        "SELECT timestamp, metric_name, value, labels FROM metrics ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()

    metrics = [
        MetricItem(
            timestamp=row[0],
            metric_name=row[1],
            value=row[2],
            labels=json.loads(row[3]) if row[3] else {},
        )
        for row in rows
    ]

    return MetricsResponse(metrics=metrics, count=len(metrics))


@router.get("/telemetry/traces/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: str,
    request: Request,
) -> TraceDetail:
    """Return full detail for a specific trace including all its events."""
    collector = _get_collector(request)

    if collector._db is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Get trace record
    cursor = await collector._db.execute(
        "SELECT trace_id, started_at, completed_at, channel, model_used, "
        "total_tokens, memory_hits, tools_invoked, success "
        "FROM traces WHERE trace_id = ?",
        (trace_id,),
    )
    row = await cursor.fetchone()

    # Get all events for this trace (even if no trace record exists)
    event_cursor = await collector._db.execute(
        "SELECT timestamp, trace_id, event_type, component, payload, duration_ms, success "
        "FROM events WHERE trace_id = ? ORDER BY timestamp ASC",
        (trace_id,),
    )
    event_rows = await event_cursor.fetchall()

    if not row and not event_rows:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")

    events = [
        EventItem(
            event_type=er[2],
            component=er[3],
            trace_id=er[1],
            payload=json.loads(er[4]) if er[4] else {},
            duration_ms=er[5],
            success=bool(er[6]),
            timestamp=er[0],
        )
        for er in event_rows
    ]

    if row:
        return TraceDetail(
            trace_id=row[0],
            started_at=row[1],
            completed_at=row[2],
            channel=row[3],
            model_used=row[4],
            total_tokens=row[5] or 0,
            memory_hits=row[6] or 0,
            tools_invoked=json.loads(row[7]) if row[7] else [],
            success=bool(row[8]),
            events=events,
        )

    # If we only have events but no trace record, synthesize from events
    timestamps = [e.timestamp for e in events]
    return TraceDetail(
        trace_id=trace_id,
        started_at=min(timestamps) if timestamps else 0,
        completed_at=max(timestamps) if timestamps else None,
        channel=None,
        model_used=None,
        total_tokens=0,
        memory_hits=0,
        tools_invoked=[],
        success=all(e.success for e in events),
        events=events,
    )
