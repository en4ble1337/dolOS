"""Observability telemetry module.

Provides the EventBus, Event dataclass, EventType enum, and EventCollector
for the agent's internal observability layer. This is the foundation for all
telemetry, tracing, and metrics in the system.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import aiosqlite

# Global context variable for trace ID propagation
_TRACE_ID_VAR: ContextVar[str] = ContextVar("trace_id", default="default")


def get_trace_id() -> str:
    """Retrieve the current trace ID from the context."""
    return _TRACE_ID_VAR.get()


def set_trace_id(trace_id: str) -> Token[str]:
    """Set the current trace ID and return a token for resetting."""
    return _TRACE_ID_VAR.set(trace_id)


def reset_trace_id(token: Token[str]) -> None:
    """Reset the trace ID to its previous state using a token."""
    _TRACE_ID_VAR.reset(token)


class RingBuffer:
    """In-memory thread-safe circular buffer for telemetry events."""

    def __init__(self, capacity: int = 1000) -> None:
        self._data: deque[Event] = deque(maxlen=capacity)

    def append(self, event: Event) -> None:
        """Add an event to the buffer, dropping the oldest if at capacity."""
        self._data.append(event)

    def get_all(self) -> list[Event]:
        """Return all events currently in the buffer."""
        return list(self._data)

    def get_recent(self, count: int) -> list[Event]:
        """Return the last 'count' events from the buffer."""
        # deque slicing is not direct; convert to list first or use itertools
        # For small counts/buffers, list conversion is fine
        all_events = self.get_all()
        return all_events[-count:] if count > 0 else []


class EventType(str, Enum):
    """All observable event types emitted by the agent."""

    # LLM
    LLM_CALL_START = "llm.call.start"
    LLM_CALL_END = "llm.call.end"
    LLM_FALLBACK = "llm.fallback"

    # Memory
    MEMORY_QUERY = "memory.query"
    MEMORY_HIT = "memory.hit"
    MEMORY_MISS = "memory.miss"
    MEMORY_WRITE = "memory.write"

    # Tools / Skills
    TOOL_INVOKE = "tool.invoke"
    TOOL_COMPLETE = "tool.complete"
    TOOL_ERROR = "tool.error"
    SKILL_INVOKE = "skill.invoke"

    # Heartbeat
    HEARTBEAT_START = "heartbeat.start"
    HEARTBEAT_COMPLETE = "heartbeat.complete"
    HEARTBEAT_MISS = "heartbeat.miss"

    # Channels
    MESSAGE_RECEIVED = "channel.message.received"
    MESSAGE_SENT = "channel.message.sent"

    # Semantic Extraction
    SEMANTIC_EXTRACTION_START = "memory.semantic.extraction.start"
    SEMANTIC_EXTRACTION_COMPLETE = "memory.semantic.extraction.complete"
    SEMANTIC_EXTRACTION_ERROR = "memory.semantic.extraction.error"
    SEMANTIC_DUPLICATE_DETECTED = "memory.semantic.duplicate"

    # Summarization
    SUMMARIZATION_START = "memory.summarization.start"
    SUMMARIZATION_COMPLETE = "memory.summarization.complete"
    SUMMARIZATION_ERROR = "memory.summarization.error"

    # Lesson Extraction
    LESSON_EXTRACTION_START = "memory.lesson.extraction.start"
    LESSON_EXTRACTION_COMPLETE = "memory.lesson.extraction.complete"
    LESSON_EXTRACTION_ERROR = "memory.lesson.extraction.error"
    LESSON_DUPLICATE_SKIPPED = "memory.lesson.duplicate"

    # Reflection (heartbeat consolidation)
    REFLECTION_START = "heartbeat.reflection.start"
    REFLECTION_COMPLETE = "heartbeat.reflection.complete"
    REFLECTION_ERROR = "heartbeat.reflection.error"

    # System
    FALLBACK_TRIGGERED = "system.fallback"
    CIRCUIT_OPEN = "system.circuit.open"
    ERROR = "system.error"


@dataclass
class Event:
    """A single telemetry event emitted by any agent component.

    Attributes:
        event_type: The type of event (use EventType enum values).
        component: Dot-separated component path, e.g. "agent.llm".
        trace_id: Unique identifier linking all events in a single request.
        payload: Arbitrary key-value data specific to this event.
        duration_ms: How long the operation took (0 if not applicable).
        success: Whether the operation succeeded.
        timestamp: Unix timestamp; auto-populated if omitted.
    """

    event_type: str
    component: str
    trace_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    success: bool = True
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Internal event bus backed by an asyncio.Queue.

    Each EventBus instance has its own queue. Components emit events
    via ``emit()`` (async) or ``emit_sync()`` (non-blocking). The
    EventCollector consumes from this queue.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    async def emit(self, event: Event) -> None:
        """Asynchronously place an event on the queue."""
        await self._queue.put(event)

    def emit_sync(self, event: Event) -> None:
        """Non-blocking put; raises ``asyncio.QueueFull`` if queue is bounded and full."""
        self._queue.put_nowait(event)


class EventCollector:
    """Consumes events from an EventBus queue and writes to SQLite.

    On ``initialize()``, creates three tables if they do not exist:

    - ``events``: individual telemetry events
    - ``metrics``: aggregated metric snapshots
    - ``traces``: end-to-end request traces
    """

    _EVENTS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            trace_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            component TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            duration_ms REAL NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 1
        )
    """

    _METRICS_SCHEMA = """
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            metric_name TEXT NOT NULL,
            value REAL NOT NULL,
            labels TEXT NOT NULL DEFAULT '{}'
        )
    """

    _TRACES_SCHEMA = """
        CREATE TABLE IF NOT EXISTS traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL UNIQUE,
            started_at REAL NOT NULL,
            completed_at REAL,
            channel TEXT,
            model_used TEXT,
            total_tokens INTEGER DEFAULT 0,
            memory_hits INTEGER DEFAULT 0,
            tools_invoked TEXT NOT NULL DEFAULT '[]',
            success INTEGER NOT NULL DEFAULT 1
        )
    """

    def __init__(self, bus: EventBus, db_path: str, buffer_capacity: int = 1000) -> None:
        self._bus = bus
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._buffer = RingBuffer(capacity=buffer_capacity)
        self._event_count = 0
        self._metrics_task: asyncio.Task | None = None
        self._callbacks: list[Callable] = []

    async def initialize(self) -> None:
        """Open (or reuse) the database connection and create tables."""
        if self._db is None:
            self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(self._EVENTS_SCHEMA)
        await self._db.execute(self._METRICS_SCHEMA)
        await self._db.execute(self._TRACES_SCHEMA)
        await self._db.commit()

    async def write_event(self, event: Event) -> None:
        """Write a single Event to the events table and in-memory buffer."""
        # Add to in-memory buffer
        self._buffer.append(event)
        self._event_count += 1

        # Notify callbacks
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception:
                # Telemetry should never crash the main loop
                pass

        if self._db is None:
            raise RuntimeError("EventCollector not initialized. Call initialize() first.")
        await self._db.execute(
            """
            INSERT INTO events (timestamp, trace_id, event_type, component, payload, duration_ms, success)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.timestamp,
                event.trace_id,
                (
                    event.event_type.value
                    if isinstance(event.event_type, EventType)
                    else event.event_type
                ),
                event.component,
                json.dumps(event.payload),
                event.duration_ms,
                int(event.success),
            ),
        )
        await self._db.commit()

    def get_recent_events(self, count: int = 100) -> list[Event]:
        """Retrieve the most recent events from the in-memory buffer."""
        return self._buffer.get_recent(count)

    def add_callback(self, callback: Callable) -> None:
        """Register a callback to be executed on every new event."""
        self._callbacks.append(callback)

    async def run_aggregation_iteration(self) -> None:
        """Calculate and write metrics for the current interval."""
        count = self._event_count
        self._event_count = 0  # Reset for next interval

        if self._db is None:
            return

        await self._db.execute(
            """
            INSERT INTO metrics (timestamp, metric_name, value, labels)
            VALUES (?, ?, ?, ?)
            """,
            (time.time(), "events_per_minute", float(count), "{}"),
        )
        await self._db.commit()

    async def _metrics_loop(self, interval: float = 60.0) -> None:
        """Continuously run aggregation every 'interval' seconds."""
        try:
            while True:
                await asyncio.sleep(interval)
                await self.run_aggregation_iteration()
        except asyncio.CancelledError:
            pass

    async def start_background_tasks(self) -> None:
        """Start the metrics aggregation background task."""
        if self._metrics_task is None:
            self._metrics_task = asyncio.create_task(self._metrics_loop())

    async def process_one(self) -> None:
        """Consume one event from the bus queue and write it to SQLite."""
        event = await self._bus._queue.get()
        await self.write_event(event)

    async def close(self) -> None:
        """Close the database connection and stop background tasks."""
        if self._metrics_task is not None:
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
            self._metrics_task = None

        if self._db is not None:
            await self._db.close()
            self._db = None
