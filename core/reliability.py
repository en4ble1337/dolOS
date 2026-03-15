"""Core reliability primitives: Circuit Breakers and Retry strategies."""

import asyncio
import functools
import random
import time
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, TypeVar

from core.telemetry import Event, EventBus, EventType

T = TypeVar("T")


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator to retry an asynchronous function with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts before raising the exception.
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay between retries in seconds.
        jitter: If True, adds randomness to the delay.
        exceptions: Tuple of exceptions that should trigger a retry.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            attempt = 1
            while True:
                try:
                    return await func(*args, **kwargs)
                except exceptions:
                    if attempt >= max_attempts:
                        raise

                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        delay = delay * random.uniform(0.5, 1.5)

                    await asyncio.sleep(delay)
                    attempt += 1

        return wrapper

    return decorator


class CircuitBreakerState(str, Enum):
    """Possible states for a Circuit Breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when the circuit is open and a call is attempted."""


class CircuitBreaker:
    """A Circuit Breaker to wrap external async calls.

    Prevents cascading failures by blocking calls when a failure threshold is reached.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        event_bus: Optional[EventBus] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.event_bus = event_bus

        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    def __call__(self, func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            self._check_state()

            if self.state == CircuitBreakerState.OPEN:
                raise CircuitOpenError(f"Circuit {self.name} is OPEN")

            try:
                result = await func(*args, **kwargs)
            except Exception:
                tripped = self._record_failure()
                if tripped and self.event_bus:
                    event = Event(
                        event_type=EventType.CIRCUIT_OPEN,
                        component=f"system.circuit_breaker.{self.name}",
                        trace_id="system",
                        payload={"state": self.state.value, "failure_count": self.failure_count},
                    )
                    await self.event_bus.emit(event)
                raise
            else:
                self._record_success()
                return result

        return wrapper

    def _check_state(self) -> None:
        """Transition from OPEN to HALF_OPEN if the reset timeout has elapsed."""
        if self.state == CircuitBreakerState.OPEN:
            if time.time() - self.last_failure_time >= self.reset_timeout:
                self.state = CircuitBreakerState.HALF_OPEN

    def _record_failure(self) -> bool:
        """Records a failure. Returns True if the circuit just tripped to OPEN."""
        self.last_failure_time = time.time()

        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
            return True
        elif self.state == CircuitBreakerState.CLOSED:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                return True

        return False

    def _record_success(self) -> None:
        """Records a success, resetting failures and closing the circuit if HALF_OPEN."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
        elif self.state == CircuitBreakerState.CLOSED:
            self.failure_count = 0
