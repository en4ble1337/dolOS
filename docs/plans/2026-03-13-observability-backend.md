# Observability Backend Implementation Plan

**Directive:** 001
**Date:** 2026-03-13
**Goal:** Build the observability backend (Phase A) — EventBus, Event types, and SQLite persistence — as the foundation layer for all future telemetry in the agent.
**Architecture Notes:** Every agent action will emit an `Event` to an `EventBus` (backed by `asyncio.Queue`). An `EventCollector` consumes that queue and writes events to SQLite via `aiosqlite`. Three tables — `events`, `metrics`, `traces` — are auto-created when the collector starts. This is a zero-dependency-on-other-modules foundation; no other my-local-agent modules need to exist for this to work.

---

### Task 1: Define `EventType` Enum

**Files:**
- Create: `core/telemetry.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/test_telemetry.py`

**Step 1:** Create test directory and `__init__.py`
- Create empty file: `tests/__init__.py`
- Create empty file: `tests/core/__init__.py`
- These are required for pytest to discover subpackage tests.
- No verification needed — these are empty marker files.

**Step 2:** Write failing test for `EventType`
- File: `tests/core/test_telemetry.py`
- Code:
```python
"""Tests for core.telemetry — EventType enum."""

from core.telemetry import EventType


class TestEventType:
    """EventType enum must define all event types from the features spec."""

    def test_event_type_is_str_enum(self):
        """EventType values should be usable as strings."""
        assert isinstance(EventType.LLM_CALL_START, str)

    def test_llm_events_exist(self):
        assert EventType.LLM_CALL_START == "llm.call.start"
        assert EventType.LLM_CALL_END == "llm.call.end"
        assert EventType.LLM_FALLBACK == "llm.fallback"

    def test_memory_events_exist(self):
        assert EventType.MEMORY_QUERY == "memory.query"
        assert EventType.MEMORY_HIT == "memory.hit"
        assert EventType.MEMORY_MISS == "memory.miss"
        assert EventType.MEMORY_WRITE == "memory.write"

    def test_tool_events_exist(self):
        assert EventType.TOOL_INVOKE == "tool.invoke"
        assert EventType.TOOL_COMPLETE == "tool.complete"
        assert EventType.TOOL_ERROR == "tool.error"
        assert EventType.SKILL_INVOKE == "skill.invoke"

    def test_heartbeat_events_exist(self):
        assert EventType.HEARTBEAT_START == "heartbeat.start"
        assert EventType.HEARTBEAT_COMPLETE == "heartbeat.complete"
        assert EventType.HEARTBEAT_MISS == "heartbeat.miss"

    def test_channel_events_exist(self):
        assert EventType.MESSAGE_RECEIVED == "channel.message.received"
        assert EventType.MESSAGE_SENT == "channel.message.sent"

    def test_system_events_exist(self):
        assert EventType.FALLBACK_TRIGGERED == "system.fallback"
        assert EventType.CIRCUIT_OPEN == "system.circuit.open"
        assert EventType.ERROR == "system.error"

    def test_total_event_count(self):
        """Ensure we have exactly the right number of event types."""
        assert len(EventType) == 17
```
- Run: `pytest tests/core/test_telemetry.py -v`
- Expected: All tests FAIL with `ImportError` (module `core.telemetry` does not exist yet).

**Step 3:** Implement `EventType` enum
- File: `core/telemetry.py`
- Code:
```python
"""Observability telemetry module.

Provides the EventBus, Event dataclass, EventType enum, and EventCollector
for the agent's internal observability layer. This is the foundation for all
telemetry, tracing, and metrics in the system.
"""

from enum import Enum


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

    # System
    FALLBACK_TRIGGERED = "system.fallback"
    CIRCUIT_OPEN = "system.circuit.open"
    ERROR = "system.error"
```
- Run: `pytest tests/core/test_telemetry.py -v`
- Expected: All 8 tests PASS.

**Step 4:** Commit
- `git add core/telemetry.py tests/__init__.py tests/core/__init__.py tests/core/test_telemetry.py`
- `git commit -m "feat(telemetry): add EventType enum with all 17 event types"`

---

### Task 2: Define `Event` Dataclass

**Files:**
- Modify: `core/telemetry.py`
- Modify: `tests/core/test_telemetry.py`

**Step 1:** Write failing tests for `Event`
- Append to `tests/core/test_telemetry.py`:
```python
import time
import uuid

from core.telemetry import Event, EventType


class TestEvent:
    """Event dataclass must hold a standard telemetry payload."""

    def test_event_creation_with_defaults(self):
        """Event should be constructable with only required fields."""
        evt = Event(
            event_type=EventType.LLM_CALL_START,
            component="agent.llm",
            trace_id="trace-abc-123",
        )
        assert evt.event_type == EventType.LLM_CALL_START
        assert evt.component == "agent.llm"
        assert evt.trace_id == "trace-abc-123"
        assert evt.payload == {}
        assert evt.duration_ms == 0.0
        assert evt.success is True
        assert isinstance(evt.timestamp, float)

    def test_event_creation_with_all_fields(self):
        """Event should accept all optional fields."""
        ts = time.time()
        evt = Event(
            event_type=EventType.TOOL_COMPLETE,
            component="tools.filesystem",
            trace_id="trace-xyz-789",
            payload={"file": "/tmp/test.txt", "bytes_read": 1024},
            duration_ms=42.5,
            success=False,
            timestamp=ts,
        )
        assert evt.payload == {"file": "/tmp/test.txt", "bytes_read": 1024}
        assert evt.duration_ms == 42.5
        assert evt.success is False
        assert evt.timestamp == ts

    def test_event_type_accepts_string(self):
        """Event.event_type should also work as a raw string for flexibility."""
        evt = Event(
            event_type="custom.event",
            component="custom",
            trace_id="t-1",
        )
        assert evt.event_type == "custom.event"

    def test_event_timestamp_auto_populated(self):
        """If timestamp is not provided, it should be close to now."""
        before = time.time()
        evt = Event(
            event_type=EventType.ERROR,
            component="system",
            trace_id="t-2",
        )
        after = time.time()
        assert before <= evt.timestamp <= after
```
- Run: `pytest tests/core/test_telemetry.py::TestEvent -v`
- Expected: All tests FAIL with `ImportError` (`Event` not yet defined).

**Step 2:** Implement `Event` dataclass
- Add to `core/telemetry.py` (after the `EventType` enum):
```python
import time
from dataclasses import dataclass, field
from typing import Any


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
```
- Note: `import time` needs to be at the top of the file. The final file layout will have all imports at the top.
- Run: `pytest tests/core/test_telemetry.py -v`
- Expected: All 12 tests PASS (8 from Task 1 + 4 from Task 2).

**Step 3:** Commit
- `git add core/telemetry.py tests/core/test_telemetry.py`
- `git commit -m "feat(telemetry): add Event dataclass with auto-timestamp"`

---

### Task 3: Implement `EventBus` Class

**Files:**
- Modify: `core/telemetry.py`
- Modify: `tests/core/test_telemetry.py`

**Step 1:** Write failing tests for `EventBus`
- Append to `tests/core/test_telemetry.py`:
```python
import asyncio
import pytest

from core.telemetry import Event, EventBus, EventType


class TestEventBus:
    """EventBus must support async and sync emission via asyncio.Queue."""

    @pytest.fixture(autouse=True)
    def fresh_bus(self):
        """Create a fresh EventBus for each test to avoid cross-test pollution."""
        self.bus = EventBus()

    def _make_event(self, event_type: EventType = EventType.LLM_CALL_START) -> Event:
        return Event(
            event_type=event_type,
            component="test",
            trace_id="test-trace",
        )

    @pytest.mark.asyncio
    async def test_emit_async_puts_event_on_queue(self):
        """Async emit should place the event on the internal queue."""
        evt = self._make_event()
        await self.bus.emit(evt)
        result = self.bus._queue.get_nowait()
        assert result is evt

    @pytest.mark.asyncio
    async def test_emit_sync_puts_event_on_queue(self):
        """Sync emit should place the event on the internal queue (non-blocking)."""
        evt = self._make_event()
        self.bus.emit_sync(evt)
        result = self.bus._queue.get_nowait()
        assert result is evt

    @pytest.mark.asyncio
    async def test_multiple_events_preserve_order(self):
        """Events should come out in FIFO order."""
        evt1 = self._make_event(EventType.LLM_CALL_START)
        evt2 = self._make_event(EventType.LLM_CALL_END)
        evt3 = self._make_event(EventType.MEMORY_QUERY)
        await self.bus.emit(evt1)
        self.bus.emit_sync(evt2)
        await self.bus.emit(evt3)

        assert self.bus._queue.get_nowait() is evt1
        assert self.bus._queue.get_nowait() is evt2
        assert self.bus._queue.get_nowait() is evt3

    @pytest.mark.asyncio
    async def test_queue_empty_after_draining(self):
        """After consuming all events, queue should be empty."""
        await self.bus.emit(self._make_event())
        self.bus._queue.get_nowait()
        assert self.bus._queue.empty()
```
- Run: `pytest tests/core/test_telemetry.py::TestEventBus -v`
- Expected: All tests FAIL with `ImportError` (`EventBus` not yet defined).

**Step 2:** Implement `EventBus`
- Add to `core/telemetry.py`:
```python
import asyncio


class EventBus:
    """Internal event bus backed by an asyncio.Queue.

    Each EventBus instance has its own queue. Components emit events
    via `emit()` (async) or `emit_sync()` (non-blocking). The
    EventCollector consumes from this queue.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    async def emit(self, event: Event) -> None:
        """Asynchronously place an event on the queue."""
        await self._queue.put(event)

    def emit_sync(self, event: Event) -> None:
        """Non-blocking put; raises asyncio.QueueFull if queue is bounded and full."""
        self._queue.put_nowait(event)
```
- Design decision: `EventBus` is an **instance** (not a class with classmethods). This enables testability — each test gets a fresh bus. A singleton/global instance can be wired at app startup.
- Run: `pytest tests/core/test_telemetry.py -v`
- Expected: All 16 tests PASS (8 + 4 + 4).

**Step 3:** Commit
- `git add core/telemetry.py tests/core/test_telemetry.py`
- `git commit -m "feat(telemetry): add EventBus with async and sync emission"`

---

### Task 4: Add `aiosqlite` Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`

**Step 1:** Add `aiosqlite` to `pyproject.toml`
- File: `pyproject.toml`
- In the `dependencies` list, add a new line after the existing `aiofiles` entry:
```toml
    "aiosqlite>=0.19.0",
```
- The `dependencies` block should end with:
```toml
    "aiofiles>=23.0.0",
    "aiosqlite>=0.19.0",
    "httpx>=0.25.0",
    "pydantic-yaml>=1.2.0",
```

**Step 2:** Add `aiosqlite` to `requirements.txt`
- File: `requirements.txt`
- Add the following line in the Utilities section (or at the end):
```
aiosqlite>=0.19.0
```

**Step 3:** Install the new dependency
- Run: `pip install aiosqlite>=0.19.0` (or `uv pip install aiosqlite>=0.19.0` if using UV)
- Expected: `Successfully installed aiosqlite-0.x.x`
- Verify: `python -c "import aiosqlite; print(aiosqlite.__version__)"`
- Expected: Prints a version like `0.19.0` or `0.20.0` without errors.

**Step 4:** Commit
- `git add pyproject.toml requirements.txt`
- `git commit -m "chore(deps): add aiosqlite for telemetry persistence"`

---

### Task 5: Implement `EventCollector` — SQLite Table Creation

**Files:**
- Modify: `core/telemetry.py`
- Modify: `tests/core/test_telemetry.py`

**Step 1:** Write failing tests for table creation
- Append to `tests/core/test_telemetry.py`:
```python
import aiosqlite
import os
import tempfile

from core.telemetry import EventCollector, EventBus


class TestEventCollectorTableCreation:
    """EventCollector must create events, metrics, and traces tables on start."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Provide a temporary SQLite DB path."""
        return str(tmp_path / "test_events.db")

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_creates_events_table(self, db_path, bus):
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "events"
        await collector.close()

    @pytest.mark.asyncio
    async def test_creates_metrics_table(self, db_path, bus):
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='metrics'"
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "metrics"
        await collector.close()

    @pytest.mark.asyncio
    async def test_creates_traces_table(self, db_path, bus):
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='traces'"
            )
            row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "traces"
        await collector.close()

    @pytest.mark.asyncio
    async def test_events_table_schema(self, db_path, bus):
        """The events table must have the correct columns."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA table_info(events)")
            columns = {row[1] for row in await cursor.fetchall()}
        expected = {"id", "timestamp", "trace_id", "event_type", "component", "payload", "duration_ms", "success"}
        assert expected == columns
        await collector.close()

    @pytest.mark.asyncio
    async def test_metrics_table_schema(self, db_path, bus):
        """The metrics table must have the correct columns."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA table_info(metrics)")
            columns = {row[1] for row in await cursor.fetchall()}
        expected = {"id", "timestamp", "metric_name", "value", "labels"}
        assert expected == columns
        await collector.close()

    @pytest.mark.asyncio
    async def test_traces_table_schema(self, db_path, bus):
        """The traces table must have the correct columns."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA table_info(traces)")
            columns = {row[1] for row in await cursor.fetchall()}
        expected = {
            "id", "trace_id", "started_at", "completed_at", "channel",
            "model_used", "total_tokens", "memory_hits", "tools_invoked", "success",
        }
        assert expected == columns
        await collector.close()

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, db_path, bus):
        """Calling initialize twice should not raise or duplicate tables."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        await collector.initialize()  # Should not raise
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            )
            row = await cursor.fetchone()
        assert row[0] == 3  # events, metrics, traces
        await collector.close()
```
- Run: `pytest tests/core/test_telemetry.py::TestEventCollectorTableCreation -v`
- Expected: All tests FAIL with `ImportError` (`EventCollector` not yet defined).

**Step 2:** Implement `EventCollector` with table creation
- Add to `core/telemetry.py`:
```python
import json
import aiosqlite


class EventCollector:
    """Consumes events from an EventBus queue and writes to SQLite.

    On initialize(), creates three tables if they do not exist:
    - events: individual telemetry events
    - metrics: aggregated metric snapshots
    - traces: end-to-end request traces
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

    def __init__(self, bus: "EventBus", db_path: str) -> None:
        self._bus = bus
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open (or reuse) the database connection and create tables."""
        if self._db is None:
            self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(self._EVENTS_SCHEMA)
        await self._db.execute(self._METRICS_SCHEMA)
        await self._db.execute(self._TRACES_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
```
- Run: `pytest tests/core/test_telemetry.py -v`
- Expected: All 23 tests PASS (16 previous + 7 new).

**Step 3:** Commit
- `git add core/telemetry.py tests/core/test_telemetry.py`
- `git commit -m "feat(telemetry): add EventCollector with SQLite table creation"`

---

### Task 6: Implement `EventCollector` — Queue Consumption and Writing

**Files:**
- Modify: `core/telemetry.py`
- Modify: `tests/core/test_telemetry.py`

**Step 1:** Write failing tests for event writing
- Append to `tests/core/test_telemetry.py`:
```python
import json


class TestEventCollectorWriting:
    """EventCollector must consume events from the bus and write to SQLite."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test_events.db")

    @pytest.fixture
    def bus(self):
        return EventBus()

    def _make_event(
        self,
        event_type: EventType = EventType.LLM_CALL_END,
        trace_id: str = "trace-001",
        component: str = "agent.llm",
        payload: dict | None = None,
        duration_ms: float = 100.0,
        success: bool = True,
    ) -> Event:
        return Event(
            event_type=event_type,
            component=component,
            trace_id=trace_id,
            payload=payload or {"model": "ollama/qwen2.5:32b"},
            duration_ms=duration_ms,
            success=success,
        )

    @pytest.mark.asyncio
    async def test_write_event_inserts_row(self, db_path, bus):
        """write_event should insert exactly one row into the events table."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        evt = self._make_event()
        await collector.write_event(evt)

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT count(*) FROM events")
            count = (await cursor.fetchone())[0]
        assert count == 1
        await collector.close()

    @pytest.mark.asyncio
    async def test_write_event_stores_correct_data(self, db_path, bus):
        """The inserted row should contain the data from the Event."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()
        evt = self._make_event(
            trace_id="trace-xyz",
            payload={"tokens_in": 100, "tokens_out": 50},
            duration_ms=250.5,
            success=False,
        )
        await collector.write_event(evt)

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM events WHERE trace_id = 'trace-xyz'")
            row = await cursor.fetchone()
        assert row["event_type"] == "llm.call.end"
        assert row["component"] == "agent.llm"
        assert json.loads(row["payload"]) == {"tokens_in": 100, "tokens_out": 50}
        assert row["duration_ms"] == 250.5
        assert row["success"] == 0  # False stored as 0
        await collector.close()

    @pytest.mark.asyncio
    async def test_process_one_consumes_from_queue(self, db_path, bus):
        """process_one should take one event from the bus queue and write it."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        evt = self._make_event()
        await bus.emit(evt)
        assert not bus._queue.empty()

        await collector.process_one()

        assert bus._queue.empty()
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT count(*) FROM events")
            count = (await cursor.fetchone())[0]
        assert count == 1
        await collector.close()

    @pytest.mark.asyncio
    async def test_process_batch(self, db_path, bus):
        """Multiple events should all be written when processed sequentially."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        for i in range(5):
            await bus.emit(self._make_event(trace_id=f"trace-{i}"))

        for _ in range(5):
            await collector.process_one()

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT count(*) FROM events")
            count = (await cursor.fetchone())[0]
        assert count == 5
        await collector.close()
```
- Run: `pytest tests/core/test_telemetry.py::TestEventCollectorWriting -v`
- Expected: All tests FAIL with `AttributeError` (`write_event` and `process_one` not yet defined).

**Step 2:** Implement `write_event` and `process_one`
- Add to `EventCollector` class in `core/telemetry.py`:
```python
    async def write_event(self, event: Event) -> None:
        """Write a single Event to the events table."""
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
                str(event.event_type),
                event.component,
                json.dumps(event.payload),
                event.duration_ms,
                int(event.success),
            ),
        )
        await self._db.commit()

    async def process_one(self) -> None:
        """Consume one event from the bus queue and write it to SQLite."""
        event = await self._bus._queue.get()
        await self.write_event(event)
```
- Run: `pytest tests/core/test_telemetry.py -v`
- Expected: All 27 tests PASS (23 previous + 4 new).

**Step 3:** Commit
- `git add core/telemetry.py tests/core/test_telemetry.py`
- `git commit -m "feat(telemetry): add EventCollector event writing and queue consumption"`

---

### Task 7: Integration Test — Full Pipeline

**Files:**
- Modify: `tests/core/test_telemetry.py`

**Step 1:** Write integration test
- Append to `tests/core/test_telemetry.py`:
```python
class TestTelemetryIntegration:
    """End-to-end: emit events → bus → collector → SQLite."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "integration_events.db")

    @pytest.mark.asyncio
    async def test_full_pipeline(self, db_path):
        """Events emitted via the bus should end up in SQLite."""
        bus = EventBus()
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        # Simulate a realistic sequence of events
        events = [
            Event(
                event_type=EventType.MESSAGE_RECEIVED,
                component="channels.telegram",
                trace_id="trace-integration-001",
                payload={"user_id": 12345, "text": "Hello agent"},
            ),
            Event(
                event_type=EventType.MEMORY_QUERY,
                component="memory.search",
                trace_id="trace-integration-001",
                payload={"query": "Hello agent", "top_k": 6},
                duration_ms=15.2,
            ),
            Event(
                event_type=EventType.MEMORY_HIT,
                component="memory.search",
                trace_id="trace-integration-001",
                payload={"results": 3, "best_score": 0.82},
            ),
            Event(
                event_type=EventType.LLM_CALL_START,
                component="agent.llm",
                trace_id="trace-integration-001",
                payload={"model": "ollama/qwen2.5:32b"},
            ),
            Event(
                event_type=EventType.LLM_CALL_END,
                component="agent.llm",
                trace_id="trace-integration-001",
                payload={"model": "ollama/qwen2.5:32b", "tokens_in": 420, "tokens_out": 183},
                duration_ms=2340.0,
                success=True,
            ),
            Event(
                event_type=EventType.MESSAGE_SENT,
                component="channels.telegram",
                trace_id="trace-integration-001",
                payload={"user_id": 12345},
            ),
        ]

        # Emit all events
        for evt in events:
            await bus.emit(evt)

        # Process all events
        for _ in range(len(events)):
            await collector.process_one()

        # Verify all events are in the database
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT count(*) FROM events")
            count = (await cursor.fetchone())[0]
            assert count == 6

            # Verify all share the same trace_id
            cursor = await db.execute(
                "SELECT DISTINCT trace_id FROM events"
            )
            trace_ids = [row[0] for row in await cursor.fetchall()]
            assert trace_ids == ["trace-integration-001"]

            # Verify event types are stored correctly
            cursor = await db.execute(
                "SELECT event_type FROM events ORDER BY id"
            )
            types = [row[0] for row in await cursor.fetchall()]
            assert types == [
                "channel.message.received",
                "memory.query",
                "memory.hit",
                "llm.call.start",
                "llm.call.end",
                "channel.message.sent",
            ]

            # Verify duration is stored for the LLM call
            cursor = await db.execute(
                "SELECT duration_ms FROM events WHERE event_type = 'llm.call.end'"
            )
            row = await cursor.fetchone()
            assert row[0] == 2340.0

        await collector.close()

    @pytest.mark.asyncio
    async def test_error_event_pipeline(self, db_path):
        """Error events with success=False should be stored correctly."""
        bus = EventBus()
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        error_event = Event(
            event_type=EventType.ERROR,
            component="agent.llm",
            trace_id="trace-err-001",
            payload={"error": "Connection refused", "model": "ollama/qwen2.5:32b"},
            success=False,
        )
        await bus.emit(error_event)
        await collector.process_one()

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM events WHERE trace_id = 'trace-err-001'")
            row = await cursor.fetchone()
            assert row["success"] == 0
            assert row["event_type"] == "system.error"
            assert "Connection refused" in row["payload"]

        await collector.close()
```
- Run: `pytest tests/core/test_telemetry.py -v`
- Expected: All 29 tests PASS (27 previous + 2 integration).

**Step 2:** Commit
- `git add tests/core/test_telemetry.py`
- `git commit -m "test(telemetry): add end-to-end integration tests for full pipeline"`

---

## Verification Plan

### Automated Tests

After all 7 tasks are complete, run the full test suite:

```bash
pytest tests/ -v --tb=short
```

**Expected output:** 29 tests, all PASS. Zero failures, zero errors.

```bash
pytest tests/ -v --cov=core --cov-report=term-missing
```

**Expected:** High coverage (90%+) on `core/telemetry.py`. Only the `close()` early-return branch and the `RuntimeError` path in `write_event` may show as uncovered by the main tests.

### Type Checking

```bash
mypy core/telemetry.py --ignore-missing-imports
```

**Expected:** `Success: no issues found`

### Linting

```bash
ruff check core/telemetry.py tests/core/test_telemetry.py
```

**Expected:** No lint errors.

### Manual Verification

No manual verification needed — this is a pure backend module with no UI component. All behavior is verified through the automated test suite.

---

## Acceptance Criteria Checklist (from Directive 001)

| Criterion | Covered By |
|-----------|-----------|
| `core/telemetry.py` is created | Task 1, Step 3 |
| `EventType` enum defined with all events from features doc | Task 1 (17 event types) |
| `Event` dataclass with standard payloads + trace IDs | Task 2 |
| `EventBus` with `asyncio.Queue` (async + sync emission) | Task 3 |
| `EventCollector` consumes queue, writes to `aiosqlite` DB | Tasks 5 & 6 |
| `events`, `metrics`, `traces` tables | Task 5 |
| Tests for all telemetry and event bus logic | Tasks 1–7 |
| SQLite tables created transparently on collector start | Task 5 (`initialize()`) |
| `aiosqlite` added to deps | Task 4 |

---

## Summary

| Task | Description | Est. Time | Tests Added |
|------|-------------|-----------|-------------|
| 1 | `EventType` enum | 3 min | 8 |
| 2 | `Event` dataclass | 3 min | 4 |
| 3 | `EventBus` class | 4 min | 4 |
| 4 | Add `aiosqlite` dep | 2 min | 0 |
| 5 | `EventCollector` — table creation | 5 min | 7 |
| 6 | `EventCollector` — queue + writing | 5 min | 4 |
| 7 | Integration tests | 3 min | 2 |
| **Total** | | **~25 min** | **29 tests** |
