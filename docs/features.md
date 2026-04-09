# dolOS Feature Reference

> Last updated: 2026-04-06 — reflects all 15 claw-gaps implemented on `feature/claw-gaps`.

---

## Core Agent Loop

**File:** `core/agent.py`

- Multi-turn LLM loop with native function calling (OpenAI tool format) and ReAct XML fallback
- Up to 10 tool-call iterations per user message before forcing a final response
- Episodic + semantic memory retrieved and injected into every turn
- Background tasks (semantic extraction, lesson extraction, summarization) fire after each turn without blocking the response

---

## Prompt Assembly (Gap 14)

**File:** `core/prompt_builder.py`

7 named sections assembled in order, each logged at DEBUG level:

| Section | Content |
|---------|---------|
| `system_bootstrap` | Tool-calling rules (native or ReAct XML based on model) |
| `identity` | `data/SOUL.md` wrapped in `<soul_instructions>` |
| `persistent_memory` | `data/LESSONS.md` + conversation summary |
| `session_memory` | Per-session K/V pairs from `SessionKVStore` |
| `working_memory` | Static files + session note (see Working Memory) |
| `retrieved_context` | Episodic + semantic memory retrieval results |
| `critical_footer` | Output-hygiene rules (always present) |

Log pattern: `[PROMPT_SECTION] <name>: <N> chars`

---

## Operator Commands (Gap 10)

**File:** `core/commands.py`

Intercepted before the LLM — no tokens consumed:

| Command | Handler |
|---------|---------|
| `/skills list` | Lists all registered skills + descriptions |
| `/doctor` | Health check of all components |
| `/memory search <q>` | Searches episodic + semantic memory |
| `/memory stats` | Collection sizes |
| `/compact` | Triggers summarization now |
| `/resume [id]` | Lists sessions or replays a transcript |
| `/plan` | Enters plan mode |
| `/approve` | Executes pending plan step-by-step |
| `/help` | Lists all commands |

---

## Plan Mode (Gap 3)

**Files:** `core/plan_mode.py`, `core/agent.py`, `core/commands.py`

- `/plan` activates `PlanModeState` on the agent
- While active, all tools are hidden from the LLM — it proposes a numbered list instead
- Steps are parsed with `^\s*\d+\.\s+(.+)$` and stored in `plan_mode_state.pending_plan`
- `/approve` exits plan mode, then calls `agent.process_message(session, step)` once per step (N round-trips, full tool access per step)
- Results returned as `**Step N:** description\n→ result`

---

## Permission Layer (Gap 1)

**File:** `skills/permissions.py`

`PermissionPolicy` dataclass controls which skills the LLM can see:

```python
PermissionPolicy(
    deny_names={"run_command"},          # block specific skills
    deny_prefixes={"internal_"},         # block by name prefix
    allow_only={"read_file", "search"},  # whitelist (overrides denies)
)
```

Applied via `filter_schemas(schemas, policy)` before schemas are passed to the LLM. Sub-agents use `allow_only` to enforce isolation.

---

## Typed Tool Contracts (Gap 2)

**File:** `skills/registry.py`

`SkillRegistration` dataclass on every registered skill:

| Field | Type | Meaning |
|-------|------|---------|
| `is_read_only` | bool | Safe to run concurrently |
| `concurrency_safe` | bool | No shared state side-effects |
| `description_fn` | callable\|None | Dynamic description based on context |

Used by the parallel tool executor and the permission layer.

---

## Parallel Read-Only Tools (Gap 11)

**File:** `core/agent.py`

When the LLM returns multiple tool calls in one response:
- Tools with `is_read_only=True` and `concurrency_safe=True` → `asyncio.gather()` (concurrent)
- All other tools → serial execution in order

Reduces latency when the agent reads multiple files or searches memory simultaneously.

---

## Dynamic Tool Routing (Gap 4)

**File:** `skills/registry.py`

When more than 10 skills are registered, `get_relevant_schemas(query, max_tools=10)` uses keyword scoring to select the most relevant subset. This prevents context bloat and keeps the LLM focused.

Log pattern: `[TOOL_ROUTING] query=... selected=N/M skills`

---

## Hook Framework (Gap 12)

**File:** `core/hooks.py`

`HookRegistry` supports two hook types:

| Hook | Behaviour |
|------|-----------|
| `pre_tool_use` | Blocking — can veto tool execution by raising `HookVeto` |
| `permission_request` | Blocking — for interactive approval flows |
| Any other name | Fire-and-forget (non-blocking background task) |

Register hooks at startup in `main.py`:
```python
hook_registry.register("pre_tool_use", my_audit_hook)
```

---

## Token Budget (Gap 9)

**Files:** `core/config.py`, `core/llm.py`, `core/agent.py`

- `MODEL_CONTEXT_WINDOW` (default 32768) set in `.env`
- `TOKEN_BUDGET_WARN_THRESHOLD` (default 0.8): logs WARNING when input tokens exceed threshold
- `TOKEN_BUDGET_SUMMARIZE_THRESHOLD` (default 0.7): triggers summarization when cumulative session tokens exceed threshold
- Cumulative session token totals tracked in `agent._session_tokens[session_id]`

Log pattern: `[TOKEN_BUDGET] Session abc: 26000/32768 input tokens (79%)`

---

## Bash Validator (Gap 7)

**File:** `skills/sandbox.py` (wired into `SandboxExecutor.execute_command()`)

Pre-flight check before any shell command executes. Blocks patterns like `rm -rf /`, `:(){ :|:& };:` (fork bombs), and other destructive commands. Returns a safe error string without executing.

---

## Session K/V Store (Gap 5)

**Files:** `memory/session_kv.py`, `skills/local/session_memory.py`

Per-session JSON-backed key-value store at `data/session_kv/<session_id>.json`. Injected into the system prompt via the `session_memory` PromptBuilder section.

Skills: `set_session_memory(session_id, key, value)` / `get_session_memory(session_id, key)`

---

## Durable Transcripts (Gap 13)

**File:** `storage/transcripts.py`

Append-only JSONL at `data/transcripts/<session_id>.jsonl`. Records 4 entry types:
- `user` — incoming message
- `assistant` — final response
- `tool_call` — tool invoked (name + arguments)
- `tool_result` — tool output (truncated to 500 chars)

Accessible via `/resume` command.

---

## Sub-Agents (Gap 6)

**Files:** `skills/local/subagent.py`, `core/task_tracker.py`

`spawn_subagent(task, tools)` creates a child `Agent` with `PermissionPolicy(allow_only=set(tools))`. The sub-agent runs synchronously (awaited inline) and returns its response as a string. Dependencies injected at startup via `set_subagent_dependencies(llm, memory, executor)`.

`TaskTracker` provides PENDING → RUNNING → DONE/FAILED lifecycle tracking for subagent coordination.

Log pattern: `[SUBAGENT] Spawning | session=subagent-abc123 | allow_only=['read_file']`

---

## MCP Server Mode (Gap 8)

**File:** `tools/mcp_server.py`

`python main.py --mcp` starts a JSON-RPC 2.0 stdio server implementing the MCP 2024-11-05 protocol:
- `initialize` / `notifications/initialized` handshake
- `tools/list` — returns all registered skills as MCP tools
- `tools/call` — invokes a skill and returns result as text content

Skill errors are returned as content (not RPC errors), per MCP spec. The normal agent mode is completely unaffected by this flag.

---

## Working Memory Files (Gap 15)

**Files:** `skills/local/session_notes.py`, `core/prompt_builder.py`, `core/agent.py`

Three static files are read from disk on every turn and injected as the `working_memory` prompt section:
- `data/CURRENT_TASK.md`
- `data/RUNBOOK.md`
- `data/KNOWN_ISSUES.md`

Additionally, the session note (`data/SESSION_NOTES/<session_id>.md`) is appended if present. All are optional — missing files are silently skipped.

Skills: `set_session_note(session_id, content)` / `get_session_note(session_id)`

Override notes directory in tests via `SESSION_NOTES_DIR` env var.

---

## Memory System

| Component | File | Description |
|-----------|------|-------------|
| Vector store | `memory/vector_store.py` | Qdrant client (local or HTTP) |
| Memory manager | `memory/memory_manager.py` | Episodic + semantic CRUD with importance scoring and recency decay |
| Session K/V | `memory/session_kv.py` | Exact-recall per-session store |
| Static loader | `memory/static_loader.py` | Chunks `USER.md`, `MEMORY.md` into semantic memory at startup |
| Summarizer | `memory/summarizer.py` | Compresses old turns when threshold is reached |
| Semantic extractor | `memory/semantic_extractor.py` | Extracts facts from each turn into semantic memory |
| Lesson extractor | `memory/lesson_extractor.py` | Detects corrections, writes `data/LESSONS.md` |
| Combined extractor | `memory/combined_extractor.py` | Single LLM call for facts + lessons (preferred) |
