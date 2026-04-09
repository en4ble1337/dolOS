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

    # check() now calls delete_by_filter for both episodic and semantic — verify
    # the episodic call is present (at least one call with collection_name='episodic').
    calls = vector_store.delete_by_filter.call_args_list
    collection_names = [
        (c.kwargs.get("collection_name") or (c.args[0] if c.args else None))
        for c in calls
    ]
    assert "episodic" in collection_names


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


# ---------------------------------------------------------------------------
# Semantic eviction tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_age_eviction_calls_delete_by_filter() -> None:
    """check() must call delete_by_filter with collection_name='semantic' for age-based eviction."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=0)
    # _count_collection uses vector_store.client.count — return 0 (below limit)
    vector_store.client = MagicMock()
    count_result = MagicMock()
    count_result.count = 0
    vector_store.client.count = MagicMock(return_value=count_result)

    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        semantic_retention_days=365,
        max_semantic_count=5000,
    )
    await task.check()

    # delete_by_filter must be called at least twice: once for episodic, once for semantic
    calls = vector_store.delete_by_filter.call_args_list
    collection_names = [
        (c.kwargs.get("collection_name") or (c.args[0] if c.args else None))
        for c in calls
    ]
    assert "semantic" in collection_names


@pytest.mark.asyncio
async def test_semantic_age_eviction_cutoff_uses_semantic_retention_days() -> None:
    """Age-based semantic cutoff must be ~(now - semantic_retention_days)."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=0)
    vector_store.client = MagicMock()
    count_result = MagicMock()
    count_result.count = 0
    vector_store.client.count = MagicMock(return_value=count_result)

    semantic_retention_days = 365
    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        semantic_retention_days=semantic_retention_days,
        max_semantic_count=5000,
    )

    before_call = time.time()
    await task.check()
    after_call = time.time()

    expected_low = before_call - (semantic_retention_days * 86400)
    expected_high = after_call - (semantic_retention_days * 86400)

    # Find the semantic call
    calls = vector_store.delete_by_filter.call_args_list
    semantic_call = next(
        c for c in calls
        if (c.kwargs.get("collection_name") or (c.args[0] if c.args else None)) == "semantic"
    )
    before_ts = semantic_call.kwargs.get("before_timestamp") or (semantic_call.args[1] if len(semantic_call.args) > 1 else None)
    assert before_ts is not None
    assert expected_low - 1 <= before_ts <= expected_high + 1


@pytest.mark.asyncio
async def test_count_based_eviction_fires_when_over_limit() -> None:
    """When semantic count > max_semantic_count, an extra delete_by_filter call is made."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=10)
    vector_store.client = MagicMock()
    count_result = MagicMock()
    count_result.count = 6000  # over the 5000 limit
    vector_store.client.count = MagicMock(return_value=count_result)

    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        max_semantic_count=5000,
        semantic_retention_days=365,
    )
    result = await task.check()

    # Count-based eviction must have fired
    assert result["semantic_count_deleted"] > 0

    # delete_by_filter called 3 times: episodic + age-semantic + count-semantic
    assert vector_store.delete_by_filter.call_count == 3


@pytest.mark.asyncio
async def test_count_based_eviction_skipped_when_under_limit() -> None:
    """When semantic count <= max_semantic_count, no count-based eviction pass runs."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=0)
    vector_store.client = MagicMock()
    count_result = MagicMock()
    count_result.count = 100  # well under the limit
    vector_store.client.count = MagicMock(return_value=count_result)

    task = MemoryMaintenanceTask(
        event_bus=event_bus,
        vector_store=vector_store,
        max_semantic_count=5000,
        semantic_retention_days=365,
    )
    result = await task.check()

    assert result["semantic_count_deleted"] == 0
    # Only 2 calls: episodic + age-semantic
    assert vector_store.delete_by_filter.call_count == 2


@pytest.mark.asyncio
async def test_semantic_result_keys_present() -> None:
    """check() result must include semantic_deleted, semantic_age_deleted, semantic_count_deleted."""
    event_bus = _make_event_bus()
    vector_store = _make_vector_store(delete_return=0)
    vector_store.client = MagicMock()
    count_result = MagicMock()
    count_result.count = 0
    vector_store.client.count = MagicMock(return_value=count_result)

    task = MemoryMaintenanceTask(event_bus=event_bus, vector_store=vector_store)
    result = await task.check()

    assert "semantic_deleted" in result
    assert "semantic_age_deleted" in result
    assert "semantic_count_deleted" in result
