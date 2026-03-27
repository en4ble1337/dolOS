# dolOS
**Local-First Autonomous AI Agent**

dolOS is a production-grade autonomous AI agent designed to run 24/7 on your own hardware. Built for privacy, persistence, and genuine capability — it executes shell commands, manages files, learns from its mistakes, and creates new skills when existing ones fall short.

Optimized for high-end local hardware (RTX 5090 + Ollama) with cloud fallback via LiteLLM.

---

## What It Actually Does

- Executes real shell commands and file operations via sandboxed skills
- Learns from corrections — mistakes are captured to `data/LESSONS.md` and injected into every future prompt
- Invents new skills on the fly using `create_skill`, which persists across restarts
- Runs 24/7 under systemd with automatic restart and Telegram/Discord escalation alerts
- Maintains episodic and semantic memory across all conversations via Qdrant
- Multi-channel: Telegram (primary), Discord, Terminal, REST API

---

## Self-Learning

When the agent encounters a task it has no skill for, it reasons from first principles:

1. Attempts to solve it using `run_code` (execute Python inline) or `run_command` (shell)
2. If the solution is reusable, it calls `create_skill` to write and register a permanent skill
3. New skills are saved to `skills/local/generated/` and auto-loaded on every restart

This means the agent's capability grows over time without manual intervention.

---

## Architecture

```
                         dolOS
                           |
          ┌────────────────┼────────────────┐
          |                |                |
      Channels           Agent           Heartbeat
   Telegram/Discord   LLM + Memory      APScheduler
    Terminal/API      + Skills          + DeadManSwitch
          |                |                |
          └────────────────┼────────────────┘
                           |
                    Ollama (local)
                  qwen3-coder:30b
                  RTX 5090 / GPU
```

**Core components:**
- `core/agent.py` — orchestrates LLM, memory, skills, and lessons
- `core/heartbeat.py` — APScheduler with pluggable integrations
- `memory/` — Qdrant vector store, episodic + semantic memory, summarizer, lesson extractor
- `skills/` — registry, executor, sandbox, and auto-generated skills
- `api/` — FastAPI routes for chat, health, memory, telemetry, skills

---

## Skills

| Skill | What it does |
|-------|-------------|
| `run_command` | Execute shell commands in a sandboxed subprocess |
| `run_code` | Execute Python code inline when no skill exists |
| `read_file` | Read file contents within the sandbox |
| `write_file` | Write files within the sandbox |
| `create_skill` | Write, register, and persist a new skill permanently |

The agent can call `create_skill` itself during a conversation — no human intervention required.

---

## Hardware

Designed for and tested on:
- **GPU**: RTX 5090 (32GB VRAM)
- **Model**: `qwen3-coder:30b` via Ollama — supports function/tool calling
- **Fallback**: Any Claude/OpenAI model via LiteLLM

Minimum viable: any machine running Ollama with a model that supports tool calling (14B+).

---

## Quick Start (Ubuntu 24.04)

```bash
# Clone
git clone https://github.com/en4ble1337/dolOS.git /opt/dolOS
cd /opt/dolOS

# Install deps
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Configure
cp .env.example .env
nano .env  # adjust PRIMARY_MODEL or channel tokens if needed

# Run
.venv/bin/python main.py
```

**As a systemd service:**
```bash
sudo cp deploy/dolOS.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dolOS
journalctl -u dolOS -f
```

---

## Configuration (`.env`)

```bash
# LLM
PRIMARY_MODEL=ollama/llama3
OLLAMA_API_BASE=http://localhost:11434

# Optional channels
# TELEGRAM_BOT_TOKEN=...
# DISCORD_BOT_TOKEN=...

# Optional alerts (dead man's switch escalation)
# TELEGRAM_ALERT_CHAT_ID=...
# DISCORD_ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Memory / Qdrant
# DATA_DIR can be a local path or an HTTP Qdrant URL.
DATA_DIR=data/qdrant_storage
SEMANTIC_EXTRACTION_ENABLED=true
SEMANTIC_SIMILARITY_THRESHOLD=0.85
SUMMARIZATION_ENABLED=true
SUMMARIZATION_TURN_THRESHOLD=10
LESSON_EXTRACTION_ENABLED=true
LESSON_CONSOLIDATION_THRESHOLD=20

# Logging
LOG_LEVEL=INFO
```

Cloud fallback keys are intentionally omitted from the default local-first setup. Re-enable them later only if you add a cloud `FALLBACK_MODEL`.

`API_TOKEN` is not used by the current Python application and is intentionally omitted.

---

## API Endpoints

All endpoints under `http://localhost:8000/api/`:

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Quick status |
| `GET /health/deep` | All components: memory, heartbeat, dead man switch |
| `POST /chat` | Send a message to the agent |
| `GET /skills` | List registered skills |
| `POST /skills/{name}/invoke` | Invoke a skill directly |
| `GET /memory/search?q=...` | Search episodic/semantic memory |
| `GET /memory/stats` | Memory usage stats |
| `GET /telemetry/events` | All telemetry events |
| `GET /telemetry/metrics` | Aggregated metrics |

Interactive docs: `http://localhost:8000/docs`

---

## Project Structure

```
dolOS/
├── core/
│   ├── agent.py          # Main orchestrator
│   ├── llm.py            # LiteLLM gateway
│   ├── config.py         # Settings (pydantic-settings)
│   ├── heartbeat.py      # APScheduler + integration registry
│   ├── alerting.py       # Telegram/Discord fire-and-forget alerts
│   └── telemetry.py      # Event bus + SQLite collector
│
├── memory/
│   ├── vector_store.py   # Qdrant client
│   ├── memory_manager.py # Episodic + semantic CRUD
│   ├── semantic_extractor.py
│   ├── summarizer.py
│   └── lesson_extractor.py  # Detects corrections, writes LESSONS.md
│
├── skills/
│   ├── registry.py       # @skill decorator + global registry
│   ├── executor.py       # Runs skills from LLM tool calls
│   ├── sandbox.py        # Subprocess sandbox with policy enforcement
│   └── local/
│       ├── filesystem.py # read_file, write_file
│       ├── system.py     # run_command, run_code
│       ├── meta.py       # create_skill
│       └── generated/    # Agent-created skills (auto-loaded)
│
├── heartbeat/integrations/
│   ├── system_health.py  # Health probe
│   ├── deadman_switch.py # Restart + escalation logic
│   └── reflection_task.py # Consolidates LESSONS.md
│
├── channels/
│   ├── terminal.py
│   ├── telegram_channel.py
│   └── discord_channel.py
│
├── api/routes/
│   ├── chat.py
│   ├── health.py
│   ├── memory.py
│   ├── skills.py
│   └── telemetry.py
│
├── data/
│   ├── SOUL.md           # Agent identity and personality
│   └── LESSONS.md        # Auto-generated behavioral corrections
│
├── deploy/
│   ├── dolOS.service     # systemd unit
│   └── .env.example      # Config template
│
├── tests/                # 221 tests, all green
└── main.py               # Entry point
```

---

## Observability

```bash
# Live logs (systemd)
journalctl -u dolOS -f

# Health check
curl http://localhost:8000/api/health/deep | python3 -m json.tool

# Test crash recovery (systemd restarts within 10s)
sudo kill -9 $(systemctl show -p MainPID --value dolOS)
sleep 12 && systemctl status dolOS
```

---

## License

MIT
