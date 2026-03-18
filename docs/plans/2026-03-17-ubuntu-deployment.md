# Ubuntu 24.04 Deployment — systemd + Headless Mode

Target: run `dolOS` as a persistent systemd service on Ubuntu 24.04, surviving reboots and process crashes.

---

## Gaps to Close

Three things block a clean headless deployment:

1. **`main()` always starts TerminalChannel** — stdin is `/dev/null` under systemd → immediate `EOFError` → server shuts down
2. **`LOG_LEVEL` is hardcoded** — should be configurable per-environment
3. **No systemd unit file**

---

## Gap 1: Headless Mode Detection

### Root Cause

`main()` calls `await terminal.start()` unconditionally. When stdin is not a TTY, `EOFError` fires immediately, the `finally` block runs `server.should_exit = True`, and the whole process exits.

### Fix

#### [MODIFY] `main.py`

Replace the unconditional terminal start with a TTY check. If headless, wait on the server task directly and handle SIGTERM for clean shutdown.

```python
import signal
import sys

async def main() -> None:
    ...
    if sys.stdin.isatty():
        # Interactive mode: terminal channel controls shutdown
        try:
            await terminal.start()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            logger.info("Terminal session exited. Shutting down...")
            server.should_exit = True
            for t in background_tasks:
                if t is not server_task:
                    t.cancel()
            try:
                await asyncio.wait([server_task], timeout=5.0)
            except Exception:
                pass
    else:
        # Headless mode: wait for server task; SIGTERM triggers shutdown
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_sigterm() -> None:
            logger.info("SIGTERM received. Shutting down...")
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)

        # Wait until SIGTERM or server dies on its own
        await asyncio.wait(
            [server_task, asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        server.should_exit = True
        for t in background_tasks:
            if t is not server_task:
                t.cancel()
        try:
            await asyncio.wait([server_task], timeout=5.0)
        except Exception:
            pass
```

**Why `sys.stdin.isatty()`:** Reliably distinguishes interactive terminals from systemd (stdin = `/dev/null`), pipes, and SSH sessions without a pseudo-TTY. No env var needed — the OS tells us.

---

## Gap 2: Configurable Log Level

### Fix

#### [MODIFY] `core/config.py`

```python
log_level: str = Field(default="INFO")
```

#### [MODIFY] `main.py`

```python
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
```

Move `settings = Settings()` above the `logging.basicConfig` call so the level is available at boot.

---

## Gap 3: systemd Unit File

### New file: `deploy/dolOS.service`

```ini
[Unit]
Description=dolOS AI Agent
Documentation=https://github.com/your-repo
After=network-online.target
Wants=network-online.target
# If Ollama runs as a separate service, add:
# After=ollama.service

[Service]
Type=simple
User=dolos
Group=dolos
WorkingDirectory=/opt/dolOS
EnvironmentFile=/opt/dolOS/.env

ExecStart=/opt/dolOS/.venv/bin/python main.py

# Restart policy: restart on crash but not on clean exit (exit code 0)
Restart=on-failure
RestartSec=10s
# Stop runaway restart loops: max 5 restarts in 2 minutes
StartLimitIntervalSec=120s
StartLimitBurst=5

# Clean shutdown: give the agent 15s to close connections
TimeoutStopSec=15s
KillMode=mixed

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

# Logging: journald captures stdout/stderr automatically
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dolOS

[Install]
WantedBy=multi-user.target
```

**Key decisions:**
- `Restart=on-failure` — restarts on crash (non-zero exit), not on clean `systemctl stop`
- `StartLimitBurst=5` — prevents infinite restart loops if something is fundamentally broken
- `KillMode=mixed` — sends SIGTERM to the main process first, then SIGKILL to the group after `TimeoutStopSec`
- Dedicated `dolos` user — least-privilege; no sudo access

---

## Log Rotation

No code changes needed. `journald` rotates logs automatically.

Default limits (Ubuntu 24.04):
- Per-service: capped at 10% of filesystem
- Global journal: auto-rotates when disk exceeds threshold

To view live logs:
```bash
journalctl -u dolOS -f
```

To query logs for a time range:
```bash
journalctl -u dolOS --since "2026-03-17 00:00" --until "2026-03-17 06:00"
```

Optional — tighten journald limits by adding to `/etc/systemd/journald.conf`:
```ini
[Journal]
SystemMaxUse=500M
MaxRetentionSec=30day
```
Then `systemctl restart systemd-journald`.

---

## Deployment Steps (Ubuntu 24.04)

### One-time setup

```bash
# 1. Create service user (no login shell, no home dir)
sudo useradd --system --no-create-home --shell /usr/sbin/nologin dolos

# 2. Create app directory
sudo mkdir -p /opt/dolOS
sudo chown dolos:dolos /opt/dolOS

# 3. Clone/copy repo
sudo -u dolos git clone <repo-url> /opt/dolOS
# or copy files

# 4. Create venv and install dependencies
sudo -u dolos python3.11 -m venv /opt/dolOS/.venv
sudo -u dolos /opt/dolOS/.venv/bin/pip install -e ".[dev]"

# 5. Create .env file (never commit this)
sudo cp /opt/dolOS/.env.example /opt/dolOS/.env
sudo chown dolos:dolos /opt/dolOS/.env
sudo chmod 600 /opt/dolOS/.env
# Edit with actual values:
sudo nano /opt/dolOS/.env

# 6. Create data directory for Qdrant persistence
sudo -u dolos mkdir -p /opt/dolOS/data/qdrant_storage

# 7. Install systemd unit
sudo cp /opt/dolOS/deploy/dolOS.service /etc/systemd/system/
sudo systemctl daemon-reload

# 8. Enable (auto-start on boot) and start
sudo systemctl enable dolOS
sudo systemctl start dolOS

# 9. Verify
sudo systemctl status dolOS
journalctl -u dolOS -f
```

### Updating the agent

```bash
sudo systemctl stop dolOS
sudo -u dolos git -C /opt/dolOS pull
sudo -u dolos /opt/dolOS/.venv/bin/pip install -e .
sudo systemctl start dolOS
```

---

## `.env.example` Template

### New file: `deploy/.env.example`

```dotenv
# LLM
PRIMARY_MODEL=ollama/llama3
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# OLLAMA_API_BASE=http://localhost:11434

# Telegram channel (optional)
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_ALERT_CHAT_ID=...   # chat ID to receive dead man's switch alerts

# Discord channel (optional)
# DISCORD_BOT_TOKEN=...
# DISCORD_ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Memory
DATA_DIR=data/qdrant_storage

# Logging
LOG_LEVEL=INFO

# Memory behaviour
SEMANTIC_EXTRACTION_ENABLED=true
SEMANTIC_SIMILARITY_THRESHOLD=0.85
SUMMARIZATION_ENABLED=true
SUMMARIZATION_TURN_THRESHOLD=10
```

---

## TDD Implementation Order

This is mostly infrastructure (no Python logic to test), but the headless mode switch is testable.

### Phase 1: Code changes
1. Move `settings = Settings()` above `logging.basicConfig` in `main.py`.
2. Add `log_level` field to `core/config.py`.
3. Update `logging.basicConfig` to use `settings.log_level`.
4. Implement headless mode detection in `main()`.

### Phase 2: Tests
`tests/test_main_headless.py`:
- `test_isatty_false_does_not_start_terminal`: mock `sys.stdin.isatty` → False, assert `terminal.start()` never called.
- `test_isatty_true_starts_terminal`: mock `sys.stdin.isatty` → True, assert `terminal.start()` called.
- `test_log_level_from_settings`: `Settings(log_level="DEBUG")` → root logger level is `DEBUG`.

### Phase 3: Deploy files
1. Create `deploy/` directory.
2. Write `deploy/dolOS.service`.
3. Write `deploy/.env.example`.
4. Run full test suite.

---

## Verification

```bash
# Service starts and stays running
sudo systemctl status dolOS
# → Active: active (running)

# Logs are flowing
journalctl -u dolOS -n 50

# Health endpoint responds
curl http://localhost:8000/api/health
# → {"status":"ok","timestamp":...}

# Deep health (all components green)
curl http://localhost:8000/api/health/deep | python3 -m json.tool

# Simulate crash: kill the process — systemd should restart within 10s
sudo kill -9 $(systemctl show -p MainPID --value dolOS)
sleep 12
sudo systemctl status dolOS
# → Active: active (running)  (restarted)
```
