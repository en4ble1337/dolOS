# Infrastructure Gaps — Skills, Heartbeat, Dead Man's Switch

Three gaps that must be closed before the agent can be considered functional:

1. **Skills not auto-loaded** — agent has zero tools at runtime
2. **Heartbeat integrations not wired** — `SystemHealthProbe` and `DeadManSwitch` exist but are never called
3. **Dead Man's Switch has no action** — fires a log warning but does nothing useful

---

## Gap 1: Skills Auto-Load

### Root Cause

`main.py` creates `registry = SkillRegistry()` — a fresh, empty instance. The `@skill` decorator registers into a **global `_default_registry`** in `skills/registry.py`. These are two different objects. The local skill modules (`filesystem.py`, `system.py`) are never imported, so their `@skill` decorators never fire. The agent runs with `tools=None` on every LLM call.

Note: `SkillExecutor.__init__` already falls back to `_default_registry` if no registry is passed — but `main.py` explicitly passes the empty `registry`, overriding the fallback.

### Fix

Two steps in `main.py` only:

**Step 1** — Replace the manually-created `SkillRegistry()` with the global default registry:

```python
from skills.registry import _default_registry as registry
```

**Step 2** — Import the local skill modules AFTER the registry import, so their `@skill` decorators fire and register into `_default_registry`:

```python
import skills.local.filesystem   # registers: read_file, write_file
import skills.local.system       # registers: run_command
```

No changes to any skill files. No new abstractions. Three lines in `main.py`.

### Context Cost

3 skills × ~150 tokens each ≈ 450 tokens per LLM call. Acceptable. Revisit with semantic skill-retrieval if the count grows past ~15.

### Tests

`tests/skills/test_autoload.py`:
- `test_local_skills_registered`: import both modules, assert `_default_registry.get_all_skill_names()` contains `read_file`, `write_file`, `run_command`.

**Note on test isolation:** `_default_registry` is a module-level global. Tests that import skill modules will mutate it permanently for the test session. Use `assert name in registry.get_all_skill_names()` (presence check) rather than `assert len(...) == 3` (exact count) to avoid fragility from test ordering.

---

## Gap 2: Wire Heartbeat Integrations

### Root Cause

`HeartbeatSystem.register_default_tasks()` defines two inline stubs returning hardcoded strings. `SystemHealthProbe` and `DeadManSwitch` are fully implemented but never scheduled. `IntegrationRegistry` in `base.py` also exists but is unused.

### Decision: IntegrationRegistry

Use `IntegrationRegistry` consistently — it is the designed pattern for this system. The heartbeat loop iterates over `registry.all()` and schedules each integration. This makes adding future integrations a one-liner (`registry.register(...)`) rather than modifying `register_default_tasks` each time.

### Fix

#### [MODIFY] `core/heartbeat.py`

Add an `IntegrationRegistry` to `HeartbeatSystem` and update `register_default_tasks` to use it:

```python
from heartbeat.integrations.base import IntegrationRegistry, HeartbeatIntegration

class HeartbeatSystem:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.scheduler = AsyncIOScheduler()
        self.integration_registry = IntegrationRegistry()
        self._running = False

    def register_integration(self, integration: HeartbeatIntegration) -> None:
        """Register an integration and schedule it."""
        self.integration_registry.register(integration)
        self.register_task(
            name=f"integration.{integration.name}",
            func=integration.check,  # call check() directly — _wrap_task handles telemetry
            trigger="interval",
            minutes=5,
        )
```

`register_default_tasks` signature — remove the unused `memory_manager` and `llm_gateway` params now that the stubs are gone. Accept the real integrations instead:

```python
def register_default_tasks(
    self,
    system_health_probe: Optional["SystemHealthProbe"] = None,
    dead_man_switch: Optional["DeadManSwitch"] = None,
) -> None:
    if system_health_probe:
        self.register_integration(system_health_probe)
    if dead_man_switch:
        self.register_integration(dead_man_switch)
```

Drop both inline stubs (`system.health_check` returning a hardcoded string, `agent.self_reflection` returning a hardcoded string). The self-reflection task will be re-added properly when RL/ReflectionTask is implemented.

**Trade-off acknowledged:** Calling `integration.check()` directly (not `integration.run()`) avoids double telemetry emission (both `_wrap_task` and `HeartbeatIntegration.run()` emit `HEARTBEAT_START`/`HEARTBEAT_COMPLETE`). The cost is losing the `@retry_with_backoff(max_attempts=2)` wrapper that `run()` provides. For `SystemHealthProbe` this means a transient disk/CPU read failure will fail without retry. This is an accepted trade-off; it can be revisited by refactoring telemetry out of `run()` if retry becomes important.

#### [MODIFY] `main.py`

```python
from heartbeat.integrations.system_health import SystemHealthProbe
from heartbeat.integrations.deadman_switch import DeadManSwitch

system_health_probe = SystemHealthProbe(event_bus=event_bus)
dead_man_switch = DeadManSwitch(
    event_bus=event_bus,
    on_restart=heartbeat.restart,      # callback pattern — see Gap 3
    alert_notifier=alert_notifier,     # see Gap 3
    max_restart_attempts=3,
)

heartbeat.register_default_tasks(
    system_health_probe=system_health_probe,
    dead_man_switch=dead_man_switch,
)
```

### Tests

`tests/heartbeat/test_heartbeat_system.py`:
- `test_register_integration_schedules_job`: call `register_integration(probe)`, assert job `"integration.system_health"` exists in scheduler.
- `test_register_default_tasks_wires_both_integrations`: after `register_default_tasks(probe, switch)`, assert both jobs scheduled.
- `test_old_stubs_removed`: assert no job named `"system.health_check"` or `"agent.self_reflection"` after `register_default_tasks`.
- `test_memory_manager_param_gone`: `register_default_tasks` signature no longer accepts `memory_manager` or `llm_gateway`.

---

## Gap 3: Dead Man's Switch — Restart + Notification

### Design Overview

When the switch fires:
1. Invoke an `on_restart` callback (up to `max_restart_attempts`, default 3)
2. If all attempts are exhausted, send an alert via `AlertNotifier`
3. The alert fires **once only** — not on every subsequent tick
4. If no notifier is configured, log CRITICAL (existing behavior)

**Key constraint:** If APScheduler dies completely, `DeadManSwitch.check()` will never be called — this only catches a degraded/slow scheduler. A fully frozen event loop requires an OS-level process manager (systemd) — explicitly out of scope.

---

### New Components

#### [MODIFY] `core/config.py`

```python
telegram_alert_chat_id: Optional[str] = Field(default=None)
discord_alert_webhook_url: Optional[str] = Field(default=None)
```

`telegram_alert_chat_id`: The Telegram user/group chat ID to send alerts to (the bot token is already configured separately).

`discord_alert_webhook_url`: A Discord webhook URL — simpler than a full bot connection for one-shot outbound alerts. Get from: Discord channel → Edit Channel → Integrations → Webhooks.

---

#### [NEW] `core/alerting.py`

A minimal, outbound-only notifier. Not a full channel — fire-and-forget messages only.

```python
class AlertNotifier:
    def __init__(self, settings: Settings) -> None:
        self._telegram_token = settings.telegram_bot_token
        self._telegram_chat_id = settings.telegram_alert_chat_id
        self._discord_webhook_url = settings.discord_alert_webhook_url

    async def send(self, message: str) -> None:
        """Send alert to all configured targets. Swallows all errors — must never crash."""
        tasks = []
        if self._telegram_token and self._telegram_chat_id:
            tasks.append(self._send_telegram(message))
        if self._discord_webhook_url:
            tasks.append(self._send_discord(message))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.warning("AlertNotifier: no targets configured, alert not sent: %s", message)

    async def _send_telegram(self, message: str) -> None:
        """One-shot send via python-telegram-bot Bot.send_message() — no polling loop."""
        try:
            from telegram import Bot
            bot = Bot(token=self._telegram_token.get_secret_value())
            await bot.send_message(chat_id=self._telegram_chat_id, text=message)
        except Exception as e:
            logger.error("AlertNotifier: Telegram send failed: %s", e)

    async def _send_discord(self, message: str) -> None:
        """One-shot POST to a Discord webhook — no gateway connection required."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                await session.post(
                    self._discord_webhook_url,
                    json={"content": message},
                )
        except Exception as e:
            logger.error("AlertNotifier: Discord send failed: %s", e)

    def is_configured(self) -> bool:
        """True if at least one alert target is configured."""
        return bool(
            (self._telegram_token and self._telegram_chat_id)
            or self._discord_webhook_url
        )
```

**Why Discord uses a webhook instead of the bot client:** The `discord.py` `Client.start()` requires a full WebSocket gateway connection (1–3s overhead, then `on_ready` wait). For a one-shot alert this is too heavy. A webhook URL is a single HTTP POST — no connection, no token required for the recipient side.

---

#### [MODIFY] `heartbeat/integrations/deadman_switch.py`

**Callback pattern instead of direct `HeartbeatSystem` reference** — avoids circular import (`deadman_switch.py` → `core.heartbeat` → `deadman_switch.py`) and avoids calling `scheduler.shutdown()` from within a running scheduled job:

```python
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from core.telemetry import Event, EventBus, EventType
from heartbeat.integrations.base import HeartbeatIntegration

if TYPE_CHECKING:
    from core.alerting import AlertNotifier

logger = logging.getLogger(__name__)

_DEFAULT_EXPECTED_INTERVAL = 30 * 60
_DEFAULT_MAX_SILENCE = 45 * 60


class DeadManSwitch(HeartbeatIntegration):
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
        self.max_silence = max_silence
        self.expected_interval = expected_interval
        self.max_restart_attempts = max_restart_attempts
        self._last_ping: float = time.time()
        self._restart_attempts: int = 0
        self._escalated: bool = False  # ensures alert fires only once

    @property
    def last_ping_elapsed(self) -> float:
        return time.time() - self._last_ping

    @property
    def restart_attempts(self) -> int:
        return self._restart_attempts

    async def check(self) -> dict[str, Any]:
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
            self._escalated = False  # reset if scheduler recovers
            result["status"] = "healthy"
            return result

        # Switch fired
        logger.critical("Dead man's switch FIRED: %.0fs since last ping (threshold %.0fs)", elapsed, self.max_silence)
        await self.event_bus.emit(Event(
            event_type=EventType.HEARTBEAT_MISS,
            component="heartbeat.integration.deadman_switch",
            trace_id="system",
            payload=result,
            success=False,
        ))

        if self._restart_attempts < self.max_restart_attempts:
            self._restart_attempts += 1
            await self._attempt_restart()
            result["status"] = "restarting"
        elif not self._escalated:
            await self._escalate()
            result["status"] = "escalated"
        else:
            result["status"] = "escalated"  # already alerted, do nothing more

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
            f"{self.max_restart_attempts} restart attempts. Manual intervention required."
        )
        logger.critical(msg)
        if self.alert_notifier:
            await self.alert_notifier.send(msg)
```

**`on_restart` callback wired in `main.py`:**

```python
dead_man_switch = DeadManSwitch(
    event_bus=event_bus,
    on_restart=heartbeat.restart,   # HeartbeatSystem.restart() = shutdown() + start()
    alert_notifier=alert_notifier,
    max_restart_attempts=3,
)
```

`HeartbeatSystem` needs a `restart()` method added:

```python
def restart(self) -> None:
    """Shut down and restart the scheduler."""
    logger.info("HeartbeatSystem: restarting scheduler.")
    self.shutdown()
    self.start()
```

---

#### [MODIFY] `api/routes/health.py`

Add heartbeat to the existing `/api/health/deep` response. No new endpoint.

```python
async def _check_heartbeat(request: Request) -> ComponentStatus:
    heartbeat = getattr(request.app.state, "heartbeat", None)
    dead_man_switch = getattr(request.app.state, "dead_man_switch", None)

    if not heartbeat or not heartbeat.is_running():
        return ComponentStatus(
            name="heartbeat", status="unhealthy",
            latency_ms=0.0, detail="Scheduler not running",
        )

    if dead_man_switch:
        elapsed = dead_man_switch.last_ping_elapsed   # uses public property
        attempts = dead_man_switch.restart_attempts   # uses public property
        if attempts == 0:
            status = "healthy"
        elif attempts < dead_man_switch.max_restart_attempts:
            status = "degraded"
        else:
            status = "unhealthy"
        detail = f"Last ping {elapsed:.0f}s ago, {attempts} restart attempt(s)"
        return ComponentStatus(name="heartbeat", status=status, latency_ms=0.0, detail=detail)

    return ComponentStatus(
        name="heartbeat", status="healthy",
        latency_ms=0.0, detail="Running (no switch configured)",
    )
```

Add `_check_heartbeat(request)` to the `components` list in `deep_health_check`.

Add to `main.py` lifespan:
```python
app.state.heartbeat = heartbeat
app.state.dead_man_switch = dead_man_switch
```

---

### Wiring Diagram

```
main.py
  ├── AlertNotifier(settings)
  ├── DeadManSwitch(on_restart=heartbeat.restart, alert_notifier=...)
  └── HeartbeatSystem
        └── APScheduler
              ├── every 5min: SystemHealthProbe.check()
              └── every 5min: DeadManSwitch.check()
                    ├── healthy  → reset _restart_attempts, _escalated
                    └── fired →
                          ├── attempts < max  → on_restart() callback
                          └── attempts >= max AND not _escalated →
                                AlertNotifier.send()
                                  ├── Telegram (Bot.send_message)
                                  └── Discord  (webhook POST)
```

---

## TDD Implementation Order

### Phase 1: Skills Autoload
1. Write `tests/skills/test_autoload.py` — presence-check 3 skills in `_default_registry`.
2. Fix `main.py` (3-line change).
3. Green.

### Phase 2: Heartbeat Wiring
1. Write `tests/heartbeat/test_heartbeat_system.py` — 4 test cases (see above).
2. Modify `core/heartbeat.py` — add `integration_registry`, `register_integration()`, `restart()`, update `register_default_tasks()`.
3. Modify `main.py` — remove old params from `register_default_tasks` call.
4. Green.

### Phase 3: AlertNotifier
1. Write `tests/core/test_alerting.py`:
   - `test_send_telegram_when_configured`: mock `Bot`, assert `send_message` called with correct chat_id.
   - `test_send_discord_webhook_when_configured`: mock `aiohttp.ClientSession`, assert POST to webhook URL.
   - `test_send_skips_unconfigured_channels`: no tokens → no sends, no crash.
   - `test_send_swallows_exceptions`: `Bot.send_message` raises → no crash, logs error.
   - `test_send_discord_swallows_exceptions`: webhook POST raises → no crash, logs error.
   - `test_is_configured_false_when_no_targets`: both None → `is_configured()` returns False.
   - `test_is_configured_true_with_telegram`: telegram token + chat_id → True.
   - `test_is_configured_true_with_discord`: webhook URL → True.
2. Implement `core/alerting.py`.
3. Modify `core/config.py` — add `telegram_alert_chat_id`, `discord_alert_webhook_url`.
4. Green.

### Phase 4: Dead Man's Switch Restart Logic
1. Write `tests/heartbeat/test_deadman_switch.py`:
   - `test_healthy_tick_resets_state`: elapsed < max_silence → `restart_attempts` stays 0, `_escalated` False, status healthy.
   - `test_fired_triggers_restart_callback`: elapsed > max_silence → `on_restart` called, attempts = 1.
   - `test_restart_counter_increments_on_each_fire`: fire three times → attempts = 3.
   - `test_escalates_after_max_attempts`: attempts reach max → `alert_notifier.send()` called once.
   - `test_escalate_fires_only_once`: fire again after max reached → `alert_notifier.send()` still called only once total (checks `_escalated` flag).
   - `test_recovery_resets_escalation`: after firing, healthy tick received → `_escalated` resets to False, `restart_attempts` resets to 0.
   - `test_no_escalation_without_notifier`: no notifier → logs CRITICAL, no crash.
   - `test_no_restart_without_callback`: `on_restart=None` → no crash, attempts still increments.
   - `test_restart_callback_failure_is_swallowed`: `on_restart` raises → no crash, logs error.
   - `test_result_dict_before_and_after_fire`: verify `result` dict keys present in both healthy and fired paths.
   - `test_public_properties`: `last_ping_elapsed` and `restart_attempts` return correct values.
2. Modify `heartbeat/integrations/deadman_switch.py`.
3. Green.

### Phase 5: Health Endpoint + Final Wiring
1. Write/update `tests/api/test_health.py`:
   - `test_deep_health_includes_heartbeat_component`: deep health response has component named `"heartbeat"`.
   - `test_heartbeat_healthy_when_scheduler_running`: mock heartbeat running, 0 attempts → status healthy.
   - `test_heartbeat_degraded_when_restarts_in_progress`: restart_attempts > 0 and < max → status degraded.
   - `test_heartbeat_unhealthy_when_max_restarts_reached`: attempts == max → status unhealthy.
2. Modify `api/routes/health.py` — add `_check_heartbeat`, add to components list.
3. Modify `main.py` — final wiring (`app.state.heartbeat`, `app.state.dead_man_switch`).
4. Run full test suite.

---

## Verification Plan

### Automated
```
pytest tests/skills/test_autoload.py
pytest tests/heartbeat/
pytest tests/core/test_alerting.py
pytest tests/api/test_health.py
```

### Manual
1. Boot agent → `GET /api/skills` returns `read_file`, `write_file`, `run_command`.
2. Ask agent to run a command → verify tool call executes and returns output.
3. `GET /api/health/deep` → `heartbeat` component present with `status: healthy`.
4. Temporarily set `max_silence=10` seconds → wait for switch to fire → verify restart logged.
5. Set `max_restart_attempts=1` + Telegram configured → let it fire → verify Telegram message received exactly once, not repeated on subsequent ticks.
