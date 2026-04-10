# dolOS
**Local-first autonomous AI agent kernel**

dolOS is a Python-based autonomous agent designed to run on your own hardware with local models by default. It combines an agent loop, persistent memory, skills/tools, telemetry, MCP integration, and multiple channels into a single local-first system that can run continuously.

Default target hardware is a high-end local GPU box (for example RTX 5090 + Ollama), with optional cloud-model fallback through LiteLLM.

## Highlights

- Real shell and file operations through sandboxed skills with a 26-pattern bash safety validator
- Episodic and semantic memory via Qdrant, plus full-text transcript search via SQLite FTS5
- Living `data/USER.md` profile maintenance and `data/LESSONS.md` behavioral learning
- Automatic skill extraction after tool-rich turns, with guarded auto-fix for generated skills
- Plan/approve workflow for higher-risk tasks
- Scoped subagents with restricted tool visibility
- MCP support in both directions:
  - expose dolOS skills as an MCP server with `--mcp`
  - connect to external MCP servers as a client
- Multiple interaction surfaces:
  - Terminal
  - Telegram
  - Discord
  - REST API
  - OpenAI-compatible `/v1/chat/completions`
- Observability stack with recent events, traces, metrics, and an optional React dashboard
- Context helpers such as `@file:`, `@folder:`, `@diff`, `@git:N`, and `@url:`

## Architecture

```text
                Channels / APIs
      Terminal | Telegram | Discord | REST | /v1
                         |
                         v
                      core/agent.py
                         |
     +-------------------+-------------------+
     |                   |                   |
     v                   v                   v
  core/llm.py       memory/*            skills/*
  LiteLLM/Ollama    Qdrant + FTS        registry + executor
                         |
                         v
              storage/transcripts.py
                         |
                         v
                core/telemetry.py
                         |
                         v
               ui/ (optional dashboard)
```

## Core Components

- `core/agent.py`
  Main orchestrator. Handles prompt construction, memory retrieval, tool loops, plan mode, parallel read-only tools, transcript writes, and background learning tasks.

- `core/llm.py`
  LiteLLM/Ollama gateway with token tracking and telemetry hooks.

- `core/prompt_builder.py`
  System prompt assembly from named sections such as identity, persistent memory, session memory, working memory, and retrieved context.

- `memory/memory_manager.py`
  Episodic + semantic memory CRUD and retrieval on top of Qdrant.

- `memory/transcript_index.py`
  SQLite FTS5 index over transcript JSONL files for exact recall via `search_transcripts`.

- `memory/user_profile_extractor.py`
  Maintains a living `data/USER.md` profile from recent interactions.

- `memory/skill_extractor.py`
  Detects reusable patterns after tool-rich turns and creates generated skills.

- `skills/executor.py`
  Executes skills, emits telemetry, and can auto-fix generated skills with guarded re-execution.

- `tools/mcp_server.py`
  Exposes the skill registry as an MCP stdio server.

- `tools/mcp_loader.py` / `tools/mcp_client.py`
  MCP client-side loading and transport/session handling.

- `ui/`
  React observability dashboard source. Served from `/` when `ui/dist` exists.

## Built-in Skills

| Skill | Read-only | Description |
|---|---|---|
| `run_command` | No | Execute shell commands in a sandboxed subprocess |
| `run_code` | No | Execute Python code inline |
| `read_file` | Yes | Read file contents |
| `write_file` | No | Write files |
| `create_skill` | No | Create and persist a new generated skill |
| `fix_skill` | Yes | Retrieve generated skill source for review/rewrite |
| `search_memory` | Yes | Query episodic or semantic memory |
| `search_transcripts` | Yes | Full-text transcript search across past sessions |
| `set_session_memory` | No | Store a key/value fact for exact session recall |
| `get_session_memory` | Yes | Retrieve a stored session key/value |
| `set_session_note` | No | Write a markdown working note for the current session |
| `get_session_note` | Yes | Read the current session note |
| `spawn_subagent` | No | Spawn a scoped subagent with restricted tool access |

Generated skills are auto-loaded from `skills/local/generated/` on startup.

## Operator Commands

Commands are intercepted before the LLM loop and do not consume model tokens.

| Command | Description |
|---|---|
| `/skills list` | List registered skills |
| `/doctor` | Health check for major subsystems |
| `/memory search <query>` | Search episodic + semantic memory |
| `/memory stats` | Show memory collection sizes |
| `/compact` | Force context compression |
| `/resume [session_id]` | List recent sessions or replay a transcript |
| `/plan` | Enter plan mode |
| `/approve` | Execute the stored plan step-by-step |
| `/help` | Show command help |

## Memory, Profiles, and Working Context

Important files under `data/`:

| File | Purpose |
|---|---|
| `data/SOUL.md` | Core agent identity and behavioral rules |
| `data/USER.md` | Living user profile maintained over time |
| `data/LESSONS.md` | Durable behavioral corrections and lessons |
| `data/CURRENT_TASK.md` | Active project/task context |
| `data/RUNBOOK.md` | Operating procedures |
| `data/KNOWN_ISSUES.md` | Known constraints or bugs |
| `data/SESSION_NOTES/<id>.md` | Per-session working notes |
| `data/transcripts/*.jsonl` | Raw transcripts per session |

`data/USER.md` and `data/MEMORY.md` are also indexed into semantic memory via `memory/static_loader.py`.

## Context Compression and References

Long sessions are compressed automatically with a 4-phase pipeline:

1. prune older tool output
2. protect head/tail context
3. summarize the middle turns
4. iteratively merge summaries

Terminal prompts also support inline context expansion:

- `@file:path`
- `@file:path:10-50`
- `@folder:path/`
- `@diff`
- `@staged`
- `@git:N`
- `@url:https://...`

Sensitive paths and oversized expansions are blocked.

## Safety Model

- Bash validator blocks 26 dangerous command patterns before execution
- Skill visibility can be restricted with permission policies
- Hooks can veto tool execution before a call runs
- Plan mode hides tools from the LLM and requires explicit `/approve`
- Generated skills are quarantined/staged before promotion

## Observability

dolOS includes an event bus, SQLite-backed collector, recent-event ring buffer, traces, metrics, and live event streaming.

Useful endpoints:

| Endpoint | Description |
|---|---|
| `GET /api/events/recent` | Recent observability events from the in-memory ring buffer |
| `WS /api/events/live` | Live event stream |
| `GET /api/telemetry/events` | Filterable telemetry events |
| `GET /api/telemetry/metrics` | Aggregated metrics |
| `GET /api/telemetry/traces/{trace_id}` | Full trace detail with associated events |

When `ui/dist` exists, FastAPI serves the React dashboard from `/`.

## API Surface

All HTTP endpoints are served from `http://localhost:8000/`.

| Endpoint | Description |
|---|---|
| `GET /api/health` | Quick health check |
| `GET /api/health/deep` | Deep subsystem health |
| `POST /api/chat` | Native chat endpoint (also supports `/commands`) |
| `GET /api/skills` | List registered skills |
| `POST /api/skills/{name}/invoke` | Invoke a skill directly |
| `GET /api/memory/search?q=...` | Search memory |
| `GET /api/memory/stats` | Memory stats |
| `POST /v1/chat/completions` | OpenAI-compatible chat endpoint |

Interactive docs are available at `http://localhost:8000/docs`.

## MCP Integration

Run dolOS as an MCP server:

```bash
python main.py --mcp
```

Normal agent mode is unaffected. In standard mode, dolOS can also connect to external MCP servers configured in `config/mcp_servers.yaml`.

## Quick Start

POSIX-style example:

```bash
git clone https://github.com/en4ble1337/dolOS.git /opt/dolOS
cd /opt/dolOS

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cp .env.example .env
nano .env

.venv/bin/python main.py
```

If you are running under Linux as a service:

```bash
sudo cp deploy/dolOS.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dolOS
journalctl -u dolOS -f
```

## Example Configuration

```bash
# LLM
PRIMARY_MODEL=ollama/qwen3-coder:30b
OLLAMA_API_BASE=http://localhost:11434
MODEL_CONTEXT_WINDOW=32768

# Optional channels
# TELEGRAM_BOT_TOKEN=...
# DISCORD_BOT_TOKEN=...

# Alerts
# TELEGRAM_ALERT_CHAT_ID=...
# DISCORD_ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Memory / Qdrant
DATA_DIR=data/qdrant_storage
SEMANTIC_EXTRACTION_ENABLED=true
SEMANTIC_SIMILARITY_THRESHOLD=0.85
SUMMARIZATION_ENABLED=true
SUMMARIZATION_TURN_THRESHOLD=10
LESSON_EXTRACTION_ENABLED=true
LESSON_CONSOLIDATION_THRESHOLD=20

# Token budget
TOKEN_BUDGET_WARN_THRESHOLD=0.8
TOKEN_BUDGET_SUMMARIZE_THRESHOLD=0.7

# Logging
LOG_LEVEL=INFO
```

## Hardware

Designed around local inference:

- GPU: RTX 5090-class system
- Default local model example: `qwen3-coder:30b` via Ollama
- Fallback: Claude/OpenAI-compatible models through LiteLLM

Minimum viable setup is any machine that can run Ollama with a tool-capable model.

## Project Structure

```text
dolOS/
├── api/
│   ├── routes/
│   └── websocket.py
├── channels/
├── core/
├── data/
├── heartbeat/
│   └── integrations/
├── memory/
├── skills/
│   └── local/
│       └── generated/
├── storage/
├── tests/
├── tools/
├── ui/
├── main.py
├── pyproject.toml
└── requirements.txt
```

## Current Status

Current baseline in this repo:

- Full pytest suite passing on the checked baseline:
  - `python -m pytest tests/ -q`
  - `671 passed` on 2026-04-09
- Self-improving agent features described in `docs/self-improving-agent-plan.md` are largely present in the codebase
- The next planned direction is a voice-first product phase built on top of dolOS as the agent kernel

Relevant planning docs:

- [`docs/self-improving-agent-plan.md`](docs/self-improving-agent-plan.md)
- [`DOLORES-VOICE-PHASE-MASTER.md`](DOLORES-VOICE-PHASE-MASTER.md)

## License

MIT
