"""Dead man's switch heartbeat integration.

Tracks the last successful heartbeat timestamp. If more than
``max_silence`` seconds elapse without a heartbeat ping, the switch
triggers, attempts a restart via callback, and escalates to alert
notification after exhausting restart attempts.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from core.telemetry import Event, EventBus, EventType
from heartbeat.integrations.base import HeartbeatIntegration

if TYPE_CHECKING:
    from core.alerting import AlertNotifier

logger = logging.getLogger(__name__)

# Default: expect a ping every 30 min, alert after 45 min of silence
_DEFAULT_EXPECTED_INTERVAL = 30 * 60  # 30 minutes
_DEFAULT_MAX_SILENCE = 45 * 60  # 45 minutes


class DeadManSwitch(HeartbeatIntegration):
    """Monitors that heartbeat pings arrive on schedule.

    When the switch fires it:
    1. Invokes ``on_restart`` callback up to ``max_restart_attempts`` times.
    2. After all attempts are exhausted, sends a one-shot alert via ``alert_notifier``.
    """

    name: str = "deadman_switch"

    def __init__(
        self,
        event_bus: EventBus,
        on_restart: Optional[Callable[[], None]] = None,
        alert_notifier: Optional["AlertNotifier"] = None,
        expected_interval: float = _DEFAULT_EXPECTED_INTERVAL,
        max_silence: float = _DEFAULT_MAX_SILENCE,
        max_restart_attempts: int = 3,
    ) -> None:
        super().__init__(event_bus)
        self.on_restart = on_restart
        self.alert_notifier = alert_notifier
        self.expected_interval = expected_interval
        self.max_silence = max_silence
        self.max_restart_attempts = max_restart_attempts
        self._last_ping: float = time.time()
        self._restart_attempts: int = 0
        self._escalated: bool = False

    @property
    def last_ping_elapsed(self) -> float:
        """Seconds since the last recorded ping."""
        return time.time() - self._last_ping

    @property
    def restart_attempts(self) -> int:
        """Number of restart attempts since the last healthy tick."""
        return self._restart_attempts

    async def check(self) -> dict[str, Any]:
        """Record a ping and check if the previous interval was too long."""
        now = time.time()
        elapsed = now - self._last_ping
        fired = elapsed > self.max_silence
        self._last_ping = now

        result: dict[str, Any] = {
            "elapsed_seconds": round(elapsed, 2),
            "max_silence_seconds": self.max_silence,
            "fired": fired,
            "restart_attempts": self._restart_attempts,
        }

        if not fired:
            self._restart_attempts = 0
            self._escalated = False
            result["status"] = "healthy"
            return result

        # Switch fired
        logger.critical(
            "Dead man's switch FIRED: %.0fs since last ping (threshold %.0fs)",
            elapsed, self.max_silence,
        )
        await self.event_bus.emit(
            Event(
                event_type=EventType.HEARTBEAT_MISS,
                component="heartbeat.integration.deadman_switch",
                trace_id="system",
                payload=result,
                success=False,
            )
        )

        if self._restart_attempts < self.max_restart_attempts:
            self._restart_attempts += 1
            result["restart_attempts"] = self._restart_attempts
            await self._attempt_restart()
            result["status"] = "restarting"
        elif not self._escalated:
            await self._escalate()
            result["status"] = "escalated"
        else:
            result["status"] = "escalated"

        return result

    async def _attempt_restart(self) -> None:
        logger.warning(
            "Attempting heartbeat restart (%d/%d)",
            self._restart_attempts, self.max_restart_attempts,
        )
        if self.on_restart:
            try:
                self.on_restart()
                logger.info("Heartbeat restart callback invoked successfully.")
            except Exception as e:
                logger.error("Heartbeat restart callback failed: %s", e)

    async def _escalate(self) -> None:
        self._escalated = True
        msg = (
            f"AGENT ALERT: Heartbeat dead man's switch failed after "
            f"{self.max_restart_attempts} restart attempt(s). Manual intervention required."
        )
        logger.critical(msg)
        if self.alert_notifier:
            await self.alert_notifier.send(msg)
