import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.reliability import (
    CircuitBreaker,
    CircuitBreakerState,
    CircuitOpenError,
    retry_with_backoff,
)
from core.telemetry import Event, EventType

# --- tests for retry_with_backoff ---


async def test_retry_success_first_try() -> None:
    mock_func = AsyncMock(return_value="success")

    @retry_with_backoff(max_attempts=3)
    async def wrapped() -> str:
        return await mock_func()  # type: ignore[no-any-return]

    result = await wrapped()
    assert result == "success"
    assert mock_func.call_count == 1


@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_retry_succeeds_after_failures(mock_sleep: AsyncMock) -> None:
    mock_func = AsyncMock(side_effect=[ValueError("fail"), ValueError("fail"), "success"])

    @retry_with_backoff(max_attempts=3, base_delay=1.0)
    async def wrapped() -> str:
        return await mock_func()  # type: ignore[no-any-return]

    result = await wrapped()
    assert result == "success"
    assert mock_func.call_count == 3
    assert mock_sleep.call_count == 2

    # Check backoff timings (jitter might change this slightly if we test exact values,
    # but we can check that sleep was called)


@patch("asyncio.sleep", new_callable=AsyncMock)
async def test_retry_fails_after_max_attempts(mock_sleep: AsyncMock) -> None:
    mock_func = AsyncMock(side_effect=ValueError("fail"))

    @retry_with_backoff(max_attempts=3)
    async def wrapped() -> Any:
        return await mock_func()

    with pytest.raises(ValueError, match="fail"):
        await wrapped()

    assert mock_func.call_count == 3
    assert mock_sleep.call_count == 2


# --- tests for CircuitBreaker ---


def test_circuit_breaker_initial_state() -> None:
    cb = CircuitBreaker("test_cb", failure_threshold=3, reset_timeout=10.0)
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.failure_count == 0


@patch("core.reliability.EventBus")
async def test_circuit_breaker_trips_to_open(mock_event_bus_class: Any) -> None:
    mock_bus = AsyncMock()

    cb = CircuitBreaker("test_cb", failure_threshold=2, reset_timeout=10.0, event_bus=mock_bus)
    mock_func = AsyncMock(side_effect=ValueError("fail"))

    wrapped = cb(mock_func)

    # First failure
    with pytest.raises(ValueError):
        await wrapped()
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.failure_count == 1

    # Second failure -> Trips to OPEN
    with pytest.raises(ValueError):
        await wrapped()
    assert cb.state == CircuitBreakerState.OPEN
    assert cb.failure_count == 2

    # Telemetry should be emitted
    mock_bus.emit.assert_called_once()
    event: Event = mock_bus.emit.call_args[0][0]
    assert event.event_type == EventType.CIRCUIT_OPEN
    assert event.component == "system.circuit_breaker.test_cb"
    assert event.payload["state"] == "OPEN"

    # Subsequent call in OPEN state fails immediately
    with pytest.raises(CircuitOpenError):
        await wrapped()


@patch("core.reliability.EventBus")
async def test_circuit_breaker_half_open_success(mock_event_bus_class: Any) -> None:
    cb = CircuitBreaker("test_cb", failure_threshold=1, reset_timeout=0.1)
    mock_func = AsyncMock(side_effect=[ValueError("fail"), "success"])
    wrapped = cb(mock_func)

    # Trip to OPEN
    with pytest.raises(ValueError):
        await wrapped()
    assert cb.state == CircuitBreakerState.OPEN

    # Wait for reset timeout
    await asyncio.sleep(0.15)

    # State should lazily transition to HALF_OPEN on next call, and if it succeeds, back to CLOSED
    result = await wrapped()
    assert result == "success"
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.failure_count == 0


@patch("core.reliability.EventBus")
async def test_circuit_breaker_half_open_failure(mock_event_bus_class: Any) -> None:
    cb = CircuitBreaker("test_cb", failure_threshold=1, reset_timeout=0.1)
    mock_func = AsyncMock(side_effect=ValueError("fail"))
    wrapped = cb(mock_func)

    # Trip to OPEN
    with pytest.raises(ValueError):
        await wrapped()

    # Wait for reset timeout
    await asyncio.sleep(0.15)

    # State transitions to HALF_OPEN, but fails again, goes back to OPEN
    with pytest.raises(ValueError):
        await wrapped()

    assert cb.state == CircuitBreakerState.OPEN
    # Emits another event or we just check state

    # Next call immediately fails with CircuitOpenError
    with pytest.raises(CircuitOpenError):
        await wrapped()
