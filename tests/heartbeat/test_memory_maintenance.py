"""Tests for MemoryMaintenanceTask heartbeat integration."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from heartbeat.integrations.memory_maintenance import MemoryMaintenanceTask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit = MagicMock()
    bus.emit_sync = MagicMock()
    return bus


def _make_vector_store(delete_return: int = 0) -> MagicMock:
    vs = MagicMock()
    vs.delete_by_filter = MagicMock(return_value=delete_return)
    return vs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_calls_delete_by_filter() -> None:
    """check() must call vector_store.delete_by_filter with collection_name='episodic'."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=0)

    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        retention_days=60,
        max_importance=0.3,
    )
    await task.check()

    vector_store.delete_by_filter.assert_called_once()
    call_kwargs = vector_store.delete_by_filter.call_args
    # Accept both positional and keyword call styles
    args, kwargs = call_kwargs
    collection = kwargs.get("collection_name") or (args[0] if args else None)
    assert collection == "episodic"


@pytest.mark.asyncio
async def test_check_returns_deleted_count() -> None:
    """check() result['deleted'] should equal the value returned by delete_by_filter."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=5)

    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        retention_days=60,
        max_importance=0.3,
    )
    result = await task.check()

    assert result["deleted"] == 5


@pytest.mark.asyncio
async def test_retention_cutoff_calculation() -> None:
    """The cutoff timestamp passed to delete_by_filter should be ~(now - 60 days)."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=0)

    retention_days = 60
    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        retention_days=retention_days,
        max_importance=0.3,
    )

    before_call = time.time()
    result = await task.check()
    after_call = time.time()

    expected_cutoff_low = before_call - (retention_days * 86400)
    expected_cutoff_high = after_call - (retention_days * 86400)

    actual_cutoff = result["cutoff"]
    # The cutoff should be within 1 second of expected
    assert expected_cutoff_low - 1 <= actual_cutoff <= expected_cutoff_high + 1, (
        f"Cutoff {actual_cutoff} not within expected range "
        f"[{expected_cutoff_low - 1}, {expected_cutoff_high + 1}]"
    )


@pytest.mark.asyncio
async def test_check_includes_retention_days_in_result() -> None:
    """check() result should include retention_days for observability."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=3)

    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        retention_days=30,
        max_importance=0.2,
    )
    result = await task.check()

    assert result["retention_days"] == 30
    assert "cutoff" in result
