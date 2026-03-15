"""Tests for core.telemetry metrics aggregation task."""

import aiosqlite
import pytest

from core.telemetry import Event, EventBus, EventCollector, EventType


class TestMetricsAggregation:
    """Background task for calculating event aggregates."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test_metrics.db")

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_metrics_task_writes_aggregates(self, db_path, bus):
        """The metrics task should count events and write to the metrics table."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        # Emit some events
        for _ in range(10):
            await collector.write_event(Event(EventType.LLM_CALL_END, "agent", "t"))

        # In a real scenario, this task would run in a loop.
        # For testing, we can expose the aggregation logic or run one iteration.
        # Let's assume a method `run_aggregation_iteration()`
        await collector.run_aggregation_iteration()

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM metrics WHERE metric_name = 'events_per_minute'"
            )
            row = await cursor.fetchone()

        assert row is not None
        assert row[3] == 10  # value column
        await collector.close()

    @pytest.mark.asyncio
    async def test_metrics_task_resets_counter_after_write(self, db_path, bus):
        """Each iteration should only count new events."""
        collector = EventCollector(bus=bus, db_path=db_path)
        await collector.initialize()

        await collector.write_event(Event(EventType.LLM_CALL_END, "agent", "t"))
        await collector.run_aggregation_iteration()

        # Second iteration with no new events
        await collector.run_aggregation_iteration()

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM metrics WHERE metric_name = 'events_per_minute' ORDER BY id DESC"
            )
            rows = await cursor.fetchall()

        assert len(rows) >= 2
        assert rows[0][0] == 0  # Most recent
        assert rows[1][0] == 1  # Previous
        await collector.close()
