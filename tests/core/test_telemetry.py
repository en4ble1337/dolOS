"""Tests for core.telemetry — EventType, Event, EventBus, and EventCollector."""

import json
import time

import aiosqlite
import pytest

from core.telemetry import Event, EventBus, EventCollector, EventType


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
        assert len(EventType) == 19


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
        expected = {
            "id",
            "timestamp",
            "trace_id",
            "event_type",
            "component",
            "payload",
            "duration_ms",
            "success",
        }
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
            "id",
            "trace_id",
            "started_at",
            "completed_at",
            "channel",
            "model_used",
            "total_tokens",
            "memory_hits",
            "tools_invoked",
            "success",
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
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('events', 'metrics', 'traces') ORDER BY name"
            )
            tables = [row[0] for row in await cursor.fetchall()]
        assert tables == ["events", "metrics", "traces"]
        await collector.close()


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


class TestTelemetryIntegration:
    """End-to-end: emit events -> bus -> collector -> SQLite."""

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
            cursor = await db.execute("SELECT DISTINCT trace_id FROM events")
            trace_ids = [row[0] for row in await cursor.fetchall()]
            assert trace_ids == ["trace-integration-001"]

            # Verify event types are stored correctly
            cursor = await db.execute("SELECT event_type FROM events ORDER BY id")
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


class TestTraceID:
    """Trace ID propagation via contextvars."""

    def test_get_trace_id_returns_default_when_unset(self):
        """If no trace ID is set, it should return a default (e.g., 'default')."""
        from core.telemetry import get_trace_id

        assert get_trace_id() == "default"

    def test_set_trace_id_updates_context(self):
        """set_trace_id should update the current context's trace ID."""
        from core.telemetry import get_trace_id, set_trace_id

        token = set_trace_id("test-trace-123")
        try:
            assert get_trace_id() == "test-trace-123"
        finally:
            # We'll need to expose the ContextVar or provide a reset mechanism
            from core.telemetry import reset_trace_id

            reset_trace_id(token)

    @pytest.mark.asyncio
    async def test_trace_id_is_task_local(self):
        """In asyncio, trace ID should be local to the task."""
        import asyncio

        from core.telemetry import get_trace_id, set_trace_id

        set_trace_id("main-trace")

        async def subtask(tid):
            set_trace_id(tid)
            await asyncio.sleep(0.01)
            return get_trace_id()

        results = await asyncio.gather(subtask("trace-A"), subtask("trace-B"))

        assert results == ["trace-A", "trace-B"]
        assert get_trace_id() == "main-trace"


class TestRingBuffer:
    """In-memory RingBuffer for recent events."""

    def test_ring_buffer_stores_events(self):
        """RingBuffer should store events up to its capacity."""
        from core.telemetry import Event, RingBuffer

        rb = RingBuffer(capacity=3)
        e1 = Event("t1", "c1", "tr1")
        e2 = Event("t2", "c2", "tr2")
        rb.append(e1)
        rb.append(e2)
        assert rb.get_all() == [e1, e2]

    def test_ring_buffer_respects_capacity(self):
        """Oldest events should be dropped when capacity is exceeded."""
        from core.telemetry import Event, RingBuffer

        rb = RingBuffer(capacity=2)
        e1 = Event("t1", "c1", "tr1")
        e2 = Event("t2", "c2", "tr2")
        e3 = Event("t3", "c3", "tr3")
        rb.append(e1)
        rb.append(e2)
        rb.append(e3)
        assert rb.get_all() == [e2, e3]

    def test_ring_buffer_get_recent_limit(self):
        """get_recent(n) should return the last n events."""
        from core.telemetry import Event, RingBuffer

        rb = RingBuffer(capacity=10)
        for i in range(5):
            rb.append(Event(f"t{i}", "c", "tr"))

        recent = rb.get_recent(2)
        assert len(recent) == 2
        assert recent[0].event_type == "t3"
        assert recent[1].event_type == "t4"


class TestEventCollectorBuffering:
    """EventCollector should store events in its in-memory RingBuffer."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test_events.db")

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_collector_stores_in_buffer(self, db_path, bus):
        """When an event is written, it should also go into the ring buffer."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        evt = Event("test.event", "test", "trace-1")
        await collector.write_event(evt)

        recent = collector.get_recent_events(1)
        assert len(recent) == 1
        assert recent[0] is evt
        await collector.close()

    @pytest.mark.asyncio
    async def test_collector_buffer_exposed_via_get_recent(self, db_path, bus):
        """EventCollector should expose a way to get recent events from its buffer."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        evts = [Event(f"e{i}", "c", "t") for i in range(5)]
        for e in evts:
            await collector.write_event(e)

        assert collector.get_recent_events(3) == evts[-3:]
        await collector.close()
