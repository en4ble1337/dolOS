# dolOS
**Local-First Autonomous AI Agent**

dolOS is a production-grade autonomous AI agent designed to run 24/7 on your own hardware. Built for privacy, persistence, and genuine capability — it executes shell commands, manages files, learns from its mistakes, creates new skills when existing ones fall short, and can delegate subtasks to scoped sub-agents.

Optimized for high-end local hardware (RTX 5090 + Ollama) with cloud fallback via LiteLLM.

---

## What It Actually Does

- Executes real shell commands and file operations via sandboxed skills with 26-pattern bash validator
- Learns from corrections — mistakes captured to `data/LESSONS.md` and injected into every future prompt
- Invents new skills on the fly using `create_skill`, persisted to `skills/local/generated/` and hot-loaded without restart
- Runs 24/7 under systemd with automatic restart and Telegram/Discord escalation alerts
- Maintains episodic and semantic memory across all conversations via Qdrant
- Proposes plans before acting (`/plan` → review → `/approve`)
- Spawns scoped sub-agents with restricted tool access for isolated subtasks
- Exposes its skill registry as an MCP server for external clients (`--mcp` mode); also connects to external MCP servers as a client
- Multi-channel: Telegram (primary), Discord, Terminal, REST API, OpenAI-compatible `/v1` endpoint
- Compresses long conversations with a 4-phase iterative compressor to stay within context limits
- Injects `@file:`, `@folder:`, `@diff`, `@git:N`, `@url:` context directly from the terminal prompt
- Extracts durable facts and behavioral lessons from every turn — both fed back into future prompts

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
- `core/agent.py` — orchestrates LLM, memory, skills, prompt building, plan mode, parallel tools, hooks, context compression
- `core/prompt_builder.py` — 7-section system prompt assembly with per-section telemetry
- `core/commands.py` — operator `/commands` intercepted before the LLM loop
- `core/hooks.py` — pre/post-tool hook registry (blocking + fire-and-forget)
- `core/plan_mode.py` — plan-then-approve state machine
- `core/task_tracker.py` — subagent task lifecycle (PENDING → RUNNING → DONE/FAILED)
- `core/context_compressor.py` — 4-phase iterative context compressor
- `core/context_refs.py` — `@`-syntax inline context injection for terminal channel
- `memory/` — Qdrant vector store, episodic + semantic memory, summarizer, lesson extractor, session K/V, combined extractor
- `skills/` — registry with typed contracts, executor, sandbox, bash validator, permissions, auto-generated skills
- `storage/transcripts.py` — append-only JSONL session transcripts
- `tools/mcp_server.py` — MCP stdio server exposing the skill registry to external clients
- `tools/mcp_loader.py` — MCP client for connecting to external MCP servers
- `api/` — FastAPI routes for chat, health, memory, telemetry, skills, OpenAI-compatible `/v1`

---

## Skills

| Skill | Read-only | Description |
|-------|-----------|-------------|
| `run_command` | No | Execute shell commands in a sandboxed subprocess |
| `run_code` | No | Execute Python code inline |
| `read_file` | Yes | Read file contents |
| `write_file` | No | Write files |
| `create_skill` | No | Write, register, and persist a new skill permanently |
| `fix_skill` | Yes | Retrieve a generated skill's source for review and rewriting |
| `search_memory` | Yes | Query episodic and semantic memory |
| `set_session_memory` | No | Store a key-value pair in session memory for exact recall |
| `get_session_memory` | Yes | Retrieve a previously stored session K/V pair |
| `set_session_note` | No | Write a markdown working note for this session |
| `get_session_note` | Yes | Read the current session note |
| `spawn_subagent` | No | Spawn a scoped sub-agent with a restricted tool set |

Agent-generated skills are auto-loaded from `skills/local/generated/` on startup.

---

## Operator Commands

Commands intercepted before the LLM loop — no tokens consumed, instant response:

| Command | Description |
|---------|-------------|
| `/skills list` | List all registered skills with descriptions |
| `/doctor` | Health check: LLM, Memory, Skill Executor, optional components |
| `/memory search <query>` | Search episodic + semantic memory |
| `/memory stats` | Show collection sizes |
| `/compact` | Trigger context compression now |
| `/resume [session_id]` | List recent sessions or replay a transcript |
| `/plan` | Enter plan mode — agent proposes steps, nothing executes |
| `/approve` | Execute the pending plan step-by-step |
| `/help` | Show this list |

---

## Plan Mode

Prevents the agent from executing destructive actions without review:

```
/plan
> Delete all log files older than 7 days

Agent: 1. Find log files older than 7 days in data/
        2. List them for confirmation
        3. Delete each file

/approve
→ Step 1 executed: found 3 files...
→ Step 2 executed: listed files...
→ Step 3 executed: deleted 3 files.
```

---

## Sub-Agents

The agent can spawn scoped sub-agents restricted to a specific tool set:

```
> Spawn a subagent to read config.yaml and summarise it

Agent: [calls spawn_subagent(task="...", tools=["read_file"])]
       Sub-agent cannot call run_command, write_file, etc.
       Returns summary inline.
```

Logs emit `[SUBAGENT] Spawning | session=subagent-abc123 | allow_only=['read_file']`.

---

## Context Compression

For long-running sessions, dolOS automatically compresses context using a 4-phase pipeline when the conversation approaches the token budget threshold:

1. **Prune** — old tool outputs beyond the tail window replaced with `[tool result omitted]`
2. **Split** — messages partitioned into protected head (system + first turn) and tail (recent N chars)
3. **Summarise** — middle messages collapsed into a structured summary via LLM: Goal / Progress / Decisions / Files Changed / Next Steps
4. **Merge** — new summary merged with any prior compression summary for coherent running history

Trigger: fires automatically when session tokens exceed 80% of context window. Also available via `/compact`.

---

## Context References (`@`-syntax)

Inject file, folder, git, or URL content inline from the terminal prompt:

```
> Review @file:core/agent.py and compare with @file:core/llm.py
> Summarise the changes in @diff
> What did commits @git:5 change?
> Fetch and summarise @url:https://example.com/spec.md
```

| Reference | Expands to |
|-----------|------------|
| `@file:path` | Full file contents |
| `@file:path:10-50` | Specific line range |
| `@folder:path/` | All files in directory |
| `@diff` | Unstaged git diff |
| `@staged` | Staged git diff |
| `@git:N` | Last N commit messages |
| `@url:https://...` | Fetched URL content (HTML stripped) |

Safety: blocks `.ssh/`, `.env`, credentials, binary files. Soft limit at 25% of context window (warns), hard limit at 50% (blocks).

---

## MCP Integration

**As a server** — expose dolOS skills to Claude Desktop, mcp-inspector, or any MCP client:

```bash
python main.py --mcp
```

Runs a JSON-RPC 2.0 stdio server implementing `initialize`, `tools/list`, and `tools/call`. Normal agent mode is unaffected.

**As a client** — connect to external MCP servers and use their tools alongside built-in skills via `tools/mcp_loader.py`.

---

## OpenAI-Compatible API

In addition to the native REST API, dolOS exposes an OpenAI-compatible endpoint:

```bash
POST http://localhost:8000/v1/chat/completions
```

Accepts the standard OpenAI wire format (`model`, `messages`, `user`). Session ID is derived from the `user` field. Compatible with any client that targets the OpenAI API, including LiteLLM proxies and local tool chains.

---

## Working Memory

Place markdown files in `data/` and they are automatically injected into every system prompt:

| File | Purpose |
|------|---------|
| `data/SOUL.md` | Agent identity, personality, and core directives |
| `data/CURRENT_TASK.md` | Active task or project context |
| `data/RUNBOOK.md` | Procedures and operational notes |
| `data/KNOWN_ISSUES.md` | Known bugs or constraints |
| `data/SESSION_NOTES/<id>.md` | Per-session notes (written by `set_session_note`) |

Visible in logs as `[PROMPT_SECTION] working_memory: N chars`.

---

## Self-Learning

dolOS has two complementary learning mechanisms that run after every turn as non-blocking background tasks:

**Fact extraction** — `SemanticExtractor` + `LessonExtractor` (combined into a single LLM call via `CombinedTurnExtractor`):
- Durable facts (preferences, decisions, technical choices) → stored in semantic memory → retrieved each future turn
- Behavioural corrections and discovered approaches → appended to `data/LESSONS.md` → injected into every system prompt
- Deduplication: similarity threshold checked before writing to avoid redundant entries
- Consolidation: `ReflectionTask` heartbeat merges lessons when count > 20 (every 5 minutes)

**Skill creation** — when the agent solves something non-trivially:
1. Writes a new Python skill via `create_skill` — full AST validation, hot-loaded immediately
2. Saved to `skills/local/generated/` — persists across restarts
3. `fix_skill` retrieves source for review and rewriting if a generated skill misbehaves

---

## Permissions & Safety

**Bash validator** — 26 dangerous command patterns blocked before any shell execution:
- Recursive deletes from root or home (`rm -rf /`, `rm -rf ~`)
- Raw device writes, system file overwrites, `chmod 777 /`
- Pipe-to-shell patterns (`curl | bash`, `wget | sh`)
- Fork bombs, disk wipe commands, crontab removal
- Remote code execution via Python/Perl/Node/Ruby eval
- Unicode control character injection

**Permission policy** — per-subagent allow/deny lists control which skills are visible to the LLM:
```python
PermissionPolicy(allow_only={"read_file", "search_memory"})  # subagent sees only these
PermissionPolicy(deny_prefixes=["delete_"])                   # block by prefix
```

**Hook registry** — blocking and fire-and-forget hooks on `pre_tool_use` and `permission_request`:
```python
# Veto any tool call starting with "delete"
async def block_delete(**kwargs):
    if kwargs.get("tool_name", "").startswith("delete"):
        raise HookVeto("delete operations are not allowed")

hooks.register("pre_tool_use", block_delete, blocking=True)
```

---

## Hardware

Designed for and tested on:
- **GPU**: RTX 5090 (32GB VRAM)
- **Model**: `qwen3-coder:30b` via Ollama — supports function/tool calling
- **Fallback**: Any Claude/OpenAI model via LiteLLM

Minimum viable: any machine running Ollama with a model that supports tool calling (14B+).

---

## Quick Start

```bash
git clone https://github.com/en4ble1337/dolOS.git /opt/dolOS
cd /opt/dolOS

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cp .env.example .env
nano .env  # set PRIMARY_MODEL and optionally channel tokens

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
PRIMARY_MODEL=ollama/qwen3-coder:30b
OLLAMA_API_BASE=http://localhost:11434
MODEL_CONTEXT_WINDOW=32768

# Optional channels
# TELEGRAM_BOT_TOKEN=...
# DISCORD_BOT_TOKEN=...

# Optional alerts (dead man's switch escalation)
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

---

## API Endpoints

All endpoints under `http://localhost:8000/`:

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Quick status |
| `GET /api/health/deep` | All components: memory, heartbeat, dead man switch |
| `POST /api/chat` | Send a message (supports `/commands`) |
| `GET /api/skills` | List registered skills |
| `POST /api/skills/{name}/invoke` | Invoke a skill directly |
| `GET /api/memory/search?q=...` | Search episodic/semantic memory |
| `GET /api/memory/stats` | Memory usage stats |
| `GET /api/telemetry/events` | All telemetry events |
| `GET /api/telemetry/metrics` | Aggregated metrics |
| `POST /v1/chat/completions` | OpenAI-compatible chat endpoint |

Interactive docs: `http://localhost:8000/docs`

---

## Project Structure

```
dolOS/
├── core/
│   ├── agent.py              # Main orchestrator
│   ├── commands.py           # Operator /commands (no LLM)
│   ├── config.py             # Settings (pydantic-settings)
│   ├── context_compressor.py # 4-phase iterative context compression
│   ├── context_refs.py       # @-syntax inline context injection
│   ├── hooks.py              # Pre/post-tool hook registry
│   ├── llm.py                # LiteLLM gateway with token tracking
│   ├── plan_mode.py          # Plan-then-approve state machine
│   ├── prompt_builder.py     # 7-section system prompt assembly
│   ├── task_tracker.py       # Subagent task lifecycle
│   ├── heartbeat.py          # APScheduler + integration registry
│   ├── alerting.py           # Telegram/Discord alerts
│   └── telemetry.py          # Event bus + SQLite collector
│
├── memory/
│   ├── vector_store.py       # Qdrant client
│   ├── memory_manager.py     # Episodic + semantic CRUD + weighted search
│   ├── session_kv.py         # Per-session key-value store
│   ├── static_loader.py      # Index USER.md / MEMORY.md into semantic memory
│   ├── semantic_extractor.py # Durable fact extraction per turn
│   ├── lesson_extractor.py   # Correction + preference extraction per turn
│   ├── combined_extractor.py # Single LLM call for facts + lessons
│   └── summarizer.py         # Periodic session summarization
│
├── skills/
│   ├── registry.py           # @skill decorator, typed contracts, tool routing
│   ├── executor.py           # Runs skills from LLM tool calls (timeout, telemetry)
│   ├── sandbox.py            # Subprocess sandbox + SandboxPolicy
│   ├── bash_validator.py     # 26-pattern dangerous command validator
│   ├── permissions.py        # PermissionPolicy (allow_only / deny lists)
│   └── local/
│       ├── filesystem.py     # read_file, write_file
│       ├── system.py         # run_command, run_code
│       ├── meta.py           # create_skill, fix_skill
│       ├── memory.py         # search_memory
│       ├── session_memory.py # set/get_session_memory
│       ├── session_notes.py  # set/get_session_note
│       ├── subagent.py       # spawn_subagent
│       └── generated/        # Agent-created skills (auto-loaded on startup)
│
├── storage/
│   └── transcripts.py        # Append-only JSONL session transcripts
│
├── tools/
│   ├── mcp_server.py         # MCP stdio server (--mcp mode)
│   └── mcp_loader.py         # MCP client (connect to external servers)
│
├── heartbeat/integrations/
│   ├── system_health.py
│   ├── deadman_switch.py
│   ├── reflection_task.py    # Lesson consolidation (every 5 min)
│   └── memory_maintenance.py
│
├── channels/
│   ├── terminal.py           # Terminal channel with @-syntax expansion
│   ├── telegram_channel.py
│   └── discord_channel.py
│
├── api/routes/
│   ├── chat.py
│   ├── v1_chat.py            # OpenAI-compatible /v1/chat/completions
│   ├── health.py
│   ├── memory.py
│   ├── skills.py
│   └── telemetry.py
│
├── data/
│   ├── SOUL.md               # Agent identity and personality
│   ├── LESSONS.md            # Auto-generated behavioral corrections
│   ├── CURRENT_TASK.md       # (optional) injected into every prompt
│   ├── RUNBOOK.md            # (optional) injected into every prompt
│   ├── KNOWN_ISSUES.md       # (optional) injected into every prompt
│   ├── session_kv/           # Per-session K/V JSON files
│   ├── SESSION_NOTES/        # Per-session markdown notes
│   └── transcripts/          # Per-session JSONL transcripts
│
├── tests/                    # 579 tests, 11 pre-existing failures (external deps)
└── main.py                   # Entry point (--mcp flag for MCP server mode)
```

---

## Observability

```bash
# Live logs (systemd)
journalctl -u dolOS -f

# Health check
curl http://localhost:8000/api/health/deep | python3 -m json.tool

# Prompt section telemetry (LOG_LEVEL=DEBUG)
# [PROMPT_SECTION] identity: 420 chars
# [PROMPT_SECTION] working_memory: 312 chars
# [PROMPT_SECTION] total: 1840 chars

# Token budget (automatic)
# [TOKEN_BUDGET] Session abc: 26000/32768 (79% of context window)

# Context compression
# [COMPRESSOR] 42 → 8 messages (summary 1840 chars)

# Tool routing
# [TOOL_ROUTING] registry=24 query="read file" selected=8/24

# Subagent traces
# [SUBAGENT] Spawning | session=subagent-abc123 | allow_only=['read_file']
# [SUBAGENT] Completed | session=subagent-abc123 | result_len=248

# Background extraction
# CombinedTurnExtractor completed in 820ms
```

---

## Roadmap — Self-Improving Agent

Full implementation plan: [`docs/self-improving-agent-plan.md`](docs/self-improving-agent-plan.md)

The next major capability is closing the "gets better over time" loop — inspired by Hermes Agent (Nous Research). The infrastructure is largely in place; what's missing is the automation that connects task outcomes back into the skill and memory systems.

### Phase A — Cross-Session Memory
Remove the `session_id` filter from semantic and lessons retrieval so accumulated knowledge is actually used across restarts. Add a `RetentionPolicy` to prevent Qdrant growing unbounded on long-running deployments.

- `memory/retention_policy.py` (new) — TTL-based episodic eviction, importance-ranked semantic pruning
- `memory/memory_manager.py` + `core/prompt_builder.py` — broaden semantic/lessons search to cross-session

### Phase B — Skill Auto-Extraction
Today `create_skill` exists but only fires when the agent is explicitly asked. This phase adds a `SkillExtractionTask` that fires automatically after every turn using ≥3 tool calls, asks the LLM "was there a reusable pattern here?", and writes a skill autonomously if yes.

- `memory/skill_extractor.py` (new) — post-turn LLM evaluation, deduplication via embedding similarity, calls `create_skill` autonomously
- `core/agent.py` — wire into `_schedule_background_tasks()`

### Phase C — Skill Self-Improvement
When a generated skill fails at runtime, `SkillExecutor` automatically reads its source, asks the LLM to fix it, rewrites it via `create_skill`, and re-executes — without human intervention.

- `skills/executor.py` — auto-fix hook on generated skill error (1 attempt max per execution)

### Phase D — Semantic Skill Routing
Replace keyword-overlap scoring in `get_relevant_schemas()` with embedding similarity so generated skills are found even when the user phrases a request differently from the skill name.

- `skills/registry.py` — embed descriptions at registration time, cosine similarity routing with keyword blend fallback

### Phase E — User Behavioral Profile
Maintain a living `data/USER.md` profile synthesized from interaction history — communication preferences, technical profile, work context, things to always/never do. Updated every 10 turns, injected into every system prompt alongside `SOUL.md`.

- `memory/user_profile_extractor.py` (new) — dialectic profile synthesis, incremental updates
- `core/prompt_builder.py` — inject `USER.md` into identity section

### Phase F — Full-Text Transcript Search
SQLite FTS5 index over the existing `data/transcripts/*.jsonl` files so the agent can verbatim-search past sessions by content, not just by vector similarity.

- `memory/transcript_index.py` (new) — FTS5 virtual table, incremental indexing on startup
- `skills/local/memory.py` — add `search_transcripts` skill

---

## License

MIT
