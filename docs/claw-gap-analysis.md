# Claude Code → dolOS: Gap Analysis & Opportunity Report

> **What this is:** A cross-reference between Anthropic's production Claude Code architecture (leaked source) and the current dolOS codebase, identifying the highest-impact patterns we don't yet have — along with concrete implementation guidance.

---

## Current dolOS Strengths (What We Already Have Well)

Before covering gaps, it's worth calling out what dolOS already does well relative to the Claude Code blueprint:

| Pattern | dolOS Status |
|---------|-------------|
| Persistent vector memory (Qdrant) | ✅ Full implementation |
| Background extraction (semantic + lesson) | ✅ Solid async task pattern |
| Lesson injection into every prompt | ✅ LESSONS.md pattern |
| Dual tool execution paths (native + ReAct XML) | ✅ Both paths wired |
| Sandbox subprocess isolation | ✅ `SandboxExecutor` with policy |
| Telemetry + trace IDs (`EventBus`) | ✅ Well-implemented |
| Multi-channel support (Telegram, Discord, Terminal) | ✅ |
| Heartbeat + dead man's switch | ✅ |
| Auto-skill creation (`create_skill`) | ✅ Unique strength |
| MCP client consumption | ✅ `mcp_client.py` present |

dolOS is not empty scaffolding — it's a functional agent. The gaps below are architectural upgrades, not basic missing pieces.

---

## Gap 1 — Explicit Permission Layer (Deny-by-Name + Deny-by-Prefix)

### What Claude Code has
A **pre-execution permission engine** that runs before any tool call fires. Tool access is controlled by:
- `deny_names`: exact match block (e.g., block `rm_file`)
- `deny_prefixes`: prefix block (e.g., block all `file_write_*`)
- Different **roles** (coordinator vs worker) get different allowlists
- Permissions are evaluated before the LLM sees the tool list — denied tools aren't even injected

### What dolOS has
The `SandboxPolicy` restricts *what code can do* at runtime (filesystem paths, network), but there's no high-level permission layer that controls *which tools the LLM is even allowed to call*. The LLM currently sees all registered skills all the time.

### Why it matters
When dolOS eventually gets subagents or exposes the agent via API to external callers, you need to scope tool access per-session or per-caller. Without a permission layer, every agent gets the full killchain including `run_command`.

### Recommended implementation
Create `skills/permissions.py`:

```python
from dataclasses import dataclass, field

@dataclass
class PermissionPolicy:
    deny_names: frozenset[str] = field(default_factory=frozenset)
    deny_prefixes: tuple[str, ...] = field(default_factory=tuple)
    allow_only: frozenset[str] | None = None  # whitelist mode

    def is_allowed(self, tool_name: str) -> bool:
        if self.allow_only is not None:
            return tool_name in self.allow_only
        if tool_name in self.deny_names:
            return False
        return not any(tool_name.startswith(p) for p in self.deny_prefixes)

    def filter_schemas(self, schemas: list[dict]) -> list[dict]:
        return [s for s in schemas if self.is_allowed(s["name"])]
```

Then thread `PermissionPolicy` into `Agent.__init__` and apply `filter_schemas()` before building the tool list for the LLM. This is a **1-2 day** implementation and the foundation for subagents.

---

## Gap 2 — Typed Tool Contracts (Dynamic Descriptions + Read/Write Metadata)

### What Claude Code has
Every tool is a **first-class typed object** with:
- `inputSchema` (validated with Zod/Pydantic)
- `isReadOnly: bool` — the harness can refuse read-only agents from calling mutating tools
- `prompt()` — description is **generated at runtime** (can include current config, available paths, etc.)
- `concurrencySafe: bool` — tools declare if they can run in parallel

### What dolOS has
Skills are registered via `@skill` decorator with a static Pydantic schema. This is a solid foundation, but descriptions are static strings baked at import time, and there's no `is_read_only` metadata the permission layer could use.

### Recommended implementation
Extend `SkillRegistration` (in `skills/registry.py`) to include:

```python
@dataclass
class SkillRegistration:
    name: str
    fn: Callable
    schema: dict
    is_read_only: bool = True          # NEW: declares mutation intent
    concurrency_safe: bool = True      # NEW: safe to run in parallel?
    description_fn: Callable[[], str] | None = None  # NEW: dynamic description
```

And update the `@skill` decorator to accept `read_only=` and `description_fn=` kwargs. This makes the permission layer useful immediately — you can deny `is_read_only=False` tools to read-only agents.

---

## Gap 3 — Plan Mode (No Execution Until Explicit Approval)

### What Claude Code has
A dedicated **plan mode** where the agent can reason, propose a plan, and request human approval before executing any mutating tools. Triggered by `EnterPlanModeTool` / `ExitPlanModeTool`. In plan mode:
- Only read-only tools are available
- The LLM produces a structured plan (markdown)
- The user reviews and approves
- Then the agent switches to execution mode

### What dolOS has
No plan mode. All tool calls execute immediately in the turn loop.

### Why it matters
For autonomous tasks (especially anything involving `write_file`, `run_command`, `create_skill`), **humans should approve the plan before execution begins**. This is the single biggest safety gap for long-horizon agentic work.

### Recommended implementation
This can be done at the agent level without upstream changes:

1. Add a `plan_mode: bool` flag to `Agent` (or pass it per-session)
2. When `plan_mode=True`, apply a read-only `PermissionPolicy` (only `read_file`, `run_command` with safe patterns)
3. Add a `plan_approve` command in the channel layer that flips the session to execution mode
4. The `data/SOUL.md` already supports persona-level instructions — add a section that tells the agent to produce a numbered plan and wait for approval when asked to do consequential work

This is **2-3 days** and makes dolOS dramatically safer for autonomous operation.

---

## Gap 4 — Dynamic Tool Routing (Context-Aware Tool Injection)

### What Claude Code has
The runtime pre-computes **semantic relevance** of tools against the current prompt before calling the LLM. Only the top-N most relevant tools are injected into the context window for that turn. This:
- Reduces token cost substantially when you have 40+ tools
- Reduces hallucination (fewer irrelevant tools = less confusion)
- Keeps the model focused

### What dolOS has
All registered skills are injected every turn regardless of query content.

### Why this matters
Currently dolOS has ~5 skills. But the README explicitly says new skills are created on the fly and auto-loaded. Over time dolOS will accumulate dozens of agent-created skills. Without routing, **every turn will include the full growing tool list**, creating noise and increasing token costs.

### Recommended implementation
Add to `skills/registry.py`:

```python
def get_relevant_schemas(self, query: str, max_tools: int = 10) -> list[dict]:
    """Return the top-N schema dicts most relevant to the query."""
    if len(self._registry) <= max_tools:
        return self.get_all_schemas()  # skip routing if small

    # Simple keyword-based relevance (no embedding cost)
    query_words = set(query.lower().split())
    scored = []
    for name, reg in self._registry.items():
        desc_words = set(reg.schema.get("description", "").lower().split())
        score = len(query_words & desc_words)
        scored.append((score, reg.schema))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:max_tools]]
```

Then replace `get_all_schemas()` calls in `agent.py` with `get_relevant_schemas(message)`. The embedding-based version (using Qdrant) comes later and is worth adding once the tool count grows past 20.

---

## Gap 5 — Session Memory Key-Value Store (Cross-Turn Fast Recall)

### What Claude Code has
A dedicated **session memory store** — a key-value map that persists across turns within a session and is injected as a compressed block into the system prompt:
- `set_memory(key, value)` — structured facts the agent writes to its own session state
- Injected as a compact block at the top of every subsequent system prompt
- Separate from the full vector memory (episodic/semantic) — this is *fast, exact recall*

### What dolOS has
episodic + semantic vector memory (great for fuzzy recall), a conversation summarizer (for long sessions), and LESSONS.md (persistent behavioral corrections). There's no fast exact-recall K/V store for within-session facts like "user's preferred language is Python" or "working on task X with branch Y".

### Why it matters
Vector search has latency and can miss exact facts. A K/V store for session-scoped facts (user preferences, active task names, current file being edited) is faster and more reliable for structured data.

### Recommended implementation
Add `memory/session_kv.py`:

```python
import json, os
from pathlib import Path

class SessionKVStore:
    """Per-session key-value store for fast, exact recall."""

    def __init__(self, data_dir: str = "data/session_kv"):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, str]] = {}

    def set(self, session_id: str, key: str, value: str) -> None:
        store = self._load(session_id)
        store[key] = value
        self._save(session_id, store)

    def get(self, session_id: str, key: str) -> str | None:
        return self._load(session_id).get(key)

    def get_all(self, session_id: str) -> dict[str, str]:
        return self._load(session_id)

    def format_for_prompt(self, session_id: str) -> str:
        store = self._load(session_id)
        if not store:
            return ""
        lines = "\n".join(f"  {k}: {v}" for k, v in store.items())
        return f"<session_memory>\n{lines}\n</session_memory>\n\n"

    def _load(self, session_id: str) -> dict[str, str]:
        if session_id not in self._cache:
            path = self._dir / f"{session_id}.json"
            self._cache[session_id] = json.loads(path.read_text()) if path.exists() else {}
        return self._cache[session_id]

    def _save(self, session_id: str, store: dict[str, str]) -> None:
        path = self._dir / f"{session_id}.json"
        path.write_text(json.dumps(store, indent=2))
        self._cache[session_id] = store
```

Inject into the system prompt alongside episodic/semantic memory. Also expose `set_session_memory` and `get_session_memory` as agent skills — let the LLM write to its own session state.

---

## Gap 6 — Subagent / Coordinator Architecture

### What Claude Code has
A full **coordinator-worker swarm**:
- `AgentTool` spawns a new agent with scoped instructions and a restricted tool allowlist
- Workers report back via structured `task-notification` messages
- Tasks have IDs, status, dependencies (blocked/running/done), and output files
- The coordinator aggregates results and continues planning

### What dolOS has
A single-agent loop. The heartbeat runs background tasks (health, reflection), but these are separate from the agent loop — they can't be *spawned by the agent on demand*.

### Why it matters
The RTX 5090 can run multiple inference contexts in parallel. Spawning lightweight read-only subagents to explore/gather while the main agent plans is a huge capability unlock — dolOS should leverage the hardware.

### Recommended implementation (phased)

**Phase A (1-2 weeks):** Add a `spawn_subagent` skill:
```python
async def spawn_subagent(task: str, tools: list[str] | None = None) -> str:
    """Spawn a focused subagent to complete a specific task. Returns the result."""
    # Create a sub-Agent with PermissionPolicy(allow_only=set(tools or []))
    # Run its turn loop with the task as the initial message
    # Return the final response
```

This is literally "run the same `Agent.process_message()` recursively with a scoped permission policy."

**Phase B (later):** Add `TaskTracker` — a simple in-memory store mapping task IDs to status/output. Expose `task_create`, `task_update`, `task_list` as skills. The coordinator (main agent) can then spawn background subagents and poll their task IDs.

---

## Gap 7 — Bash/Shell AST-Level Security Validation

### What Claude Code has
23 distinct security checks on every bash command *before* execution:
- Quote extraction (single, double, unquoted)  
- Command substitution detection (`$()`, backticks)
- IFS manipulation detection
- Heredoc trick detection
- Unicode control character detection
- Tree-sitter AST parsing for structural analysis

### What dolOS has
The `SandboxExecutor` runs commands in a subprocess with timeout + path restrictions, but does **not** validate the command content before executing it. An LLM generating `rm -rf /` would run (it would fail due to path restrictions, but `rm -rf data/` would work fine).

### Why it matters
LLMs hallucinate dangerous commands. dolOS already creates agent-generated skills that call `run_command` — this surface deserves hardened pre-validation, not just runtime isolation.

### Recommended implementation
Create `skills/bash_validator.py`:

```python
import re
from dataclasses import dataclass

DANGEROUS_PATTERNS = [
    (r"\brm\s+-[rf]+\s+/", "destructive recursive delete from root"),
    (r"\bdd\b.*of=/dev/", "raw device write"),
    (r">\s*/etc/", "overwrite system file"),
    (r"\bchmod\s+777\s+/", "world-write root"),
    (r"\|\s*sh\b", "pipe to shell"),
    (r"\|\s*bash\b", "pipe to bash"),
    (r"\bcurl\b.*\|\s*(sh|bash)", "remote code execution via curl-pipe"),
    (r"\$\(.*\)", "command substitution"),
    (r"`[^`]*`", "backtick substitution"),
    # Add more as discovered
]

@dataclass
class ValidationResult:
    is_safe: bool
    reason: str = ""

def validate_bash_command(command: str) -> ValidationResult:
    for pattern, reason in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return ValidationResult(is_safe=False, reason=reason)
    return ValidationResult(is_safe=True)
```

Wire this into `SandboxExecutor.execute_command()` as a pre-flight check. If not safe, return an error dict without executing. This is a **half-day** implementation that significantly raises the security floor.

---

## Gap 8 — MCP Server Exposure (Expose dolOS Tools Over MCP)

### What Claude Code has
Claude Code **exposes all its own tools as an MCP server** — meaning any MCP-compatible client can call dolOS tools without knowing the internal implementation. It also *consumes* external MCP servers.

### What dolOS has
`tools/mcp_client.py` — dolOS can **consume** MCP servers. But dolOS doesn't **expose itself** as an MCP server.

### Why it matters
Exposing dolOS over MCP means:
- Any MCP client (including other AI tools) can call dolOS skills
- dolOS becomes part of the composable MCP ecosystem
- The REST API becomes redundant for tool consumers — they use MCP instead
- Future multi-agent setups can wire dolOS subagents via MCP without custom protocols

### Recommended implementation
The `mcp` Python SDK makes this straightforward. Create `tools/mcp_server.py`:

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from skills.registry import global_registry

app = Server("dolOS")

@app.list_tools()
async def list_tools():
    return [build_mcp_tool(schema) for schema in global_registry.get_all_schemas()]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    result = await skill_executor.execute(name, arguments, trace_id="mcp")
    return [TextContent(type="text", text=str(result))]
```

Add a `--mcp` startup flag to `main.py` that routes to `stdio_server(app)`. This is a **1-2 day** implementation and should be on the roadmap.

---

## Gap 9 — Token Budget Controls + Context Compaction Trigger

### What Claude Code has
The turn loop tracks **input and output token consumption per turn** and has explicit budget policies:
- `compact_after_turns: int` — trigger compaction (summary of old messages) after N turns
- `token_budget_continuation` — if the model hits output token limit mid-thought, the loop continues with a "continue from where you left off" injection
- Each subagent gets a **per-agent token budget** so a runaway worker can't consume unlimited tokens

### What dolOS has
The summarizer triggers at `SUMMARIZATION_TURN_THRESHOLD` (default 10 turns) — good. But there's no token counting, no per-turn budget, and the turn loop doesn't detect or handle mid-output truncation.

### Why it matters
Without token counting, dolOS can send context windows that overflow without warning, causing silent truncation. The model silently loses context and starts hallucinating "nothing happened" for tool calls it no longer has in window.

### Recommended implementation
LiteLLM returns `usage` in responses. Capture it in `LLMGateway.generate()`:

```python
# In generate() response handling:
if hasattr(response, "usage") and response.usage:
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    # Emit TELEMETRY event with token counts
    # Store in session for per-session budget tracking
```

Then in `agent.py`, track cumulative token cost per session and log a warning when approaching 80% of the model's context window. The compaction trigger can be updated to also trigger on token count, not just turn count.

---

## Priority Matrix

| Gap | Impact | Effort | Priority |
|-----|--------|--------|----------|
| **Gap 7: Bash AST Validation** | 🔴 Safety | 🟢 0.5 day | **Immediate** |
| **Gap 4: Dynamic Tool Routing** | 🟡 Scalability | 🟢 1 day | **Soon** |
| **Gap 1: Permission Layer** | 🔴 Safety + Architecture | 🟡 1-2 days | **Soon** |
| **Gap 5: Session K/V Memory** | 🟡 Capability | 🟡 1-2 days | **Soon** |
| **Gap 9: Token Budget Controls** | 🟡 Reliability | 🟡 2 days | **Soon** |
| **Gap 2: Typed Tool Contracts** | 🟡 Architecture | 🟡 1-2 days | **Next sprint** |
| **Gap 3: Plan Mode** | 🔴 Safety for autonomy | 🟡 2-3 days | **Next sprint** |
| **Gap 8: MCP Server Exposure** | 🟢 Ecosystem | 🟡 1-2 days | **After Plan Mode** |
| **Gap 6: Subagent / Coordinator** | 🟢 Capability | 🔴 2-3 weeks | **Roadmap** |

---

## What dolOS Has That Claude Code Doesn't

It's also worth noting where dolOS is **ahead of the Claude Code architecture** for its use case:

| dolOS Feature | Advantage |
|--------------|-----------|
| **LESSONS.md injection** | Behavioral correction loop that Claude Code lacks entirely |
| **Auto-skill creation** (`create_skill`) | Self-extending capability without redeploy |
| **Qwen3 ReAct XML fallback** | Supports models that predate native tool calling |
| **Local-first / Ollama-native** | No cloud dependency, no cost per call at runtime |
| **Dead man's switch** | Production-grade 24/7 monitoring not present in Claude Code |
| **Combined extractor** | Single LLM call for facts + lessons vs. two separate calls |

---

*Generated: 2026-04-06 | Source: claw-code executive summaries + dolOS codebase review*

---

## Appendix — Additional Must-Have Gaps (Source Pass Addendum)

These are the **additional** gaps I would append after reading both the existing dolOS implementation and the actual `claw-code` source. They are intentionally limited to the highest-signal items that are **not already covered** by Gaps 1-9 above.

---

## Gap 10 — Deterministic Operator Command Layer

### What Claude Code has
A dedicated **command plane** separate from LLM tool use:
- `/compact`
- `/memory`
- `/tasks`
- `/permissions`
- `/doctor`
- `/resume`
- `/model`

These commands are deterministic operator actions, not natural-language requests that must go through the model.

### What dolOS has
Terminal and API input currently flow straight into the agent loop:
- `channels/terminal.py` sends user input directly to `Agent.process_message()`
- `api/routes/chat.py` exposes only raw chat

There is no separate operator command layer.

### Why it matters
Not everything should be an LLM turn. Operator-style actions are:
- cheaper
- faster
- more reliable
- easier to audit

Without a command layer, even simple control actions like inspecting memory, forcing summarization, or listing tasks become prompt-engineering problems.

### Recommended implementation
Add a lightweight command router in the channel/API layer:
- `/memory search <query>`
- `/memory stats`
- `/compact`
- `/skills`
- `/tasks`
- `/permissions`
- `/model`
- `/doctor`

This is a **high-leverage, low-effort** addition and should land before subagents.

---

## Gap 11 — Parallel Read-Only Tool Orchestration

### What Claude Code has
The tool runtime can batch **concurrency-safe** tool calls in parallel:
- read-only/search tools run concurrently
- mutating tools run serially
- tools declare whether they are concurrency-safe

This makes exploration agents dramatically faster.

### What dolOS has
Tool calls execute serially inside the main loop. Even obviously parallel-safe work like:
- multiple file reads
- multiple grep/glob calls
- multiple MCP lookups

will happen one at a time.

### Why it matters
Once dolOS grows beyond a handful of tools, serial orchestration becomes unnecessary latency. This is especially wasteful for:
- codebase exploration
- retrieval-heavy tasks
- future MCP-heavy workflows

### Recommended implementation
Extend skill metadata with:
- `is_read_only: bool`
- `concurrency_safe: bool`

Then update the execution loop to:
1. partition tool calls into safe concurrent batches vs mutating calls
2. run read-only batches with `asyncio.gather(...)`
3. apply any context mutations only after the batch completes

This pairs naturally with Gap 2's typed tool contracts.

---

## Gap 12 — Hook / Automation Framework

### What Claude Code has
A configurable hook system around major lifecycle events:
- `PreToolUse`
- `PostToolUse`
- `PermissionRequest`
- `SessionStart`
- `Stop`
- `SubagentStart`
- `TaskCreated`

This lets the harness enforce local policy and automation without hardcoding behavior into the main agent loop.

### What dolOS has
dolOS has good telemetry, but no general hook/event automation framework. That means policy and workflow logic can only live in:
- the agent prompt
- the skill implementation
- ad hoc application code

### Why it matters
Hooks give you a clean place to implement:
- repo-specific policy
- prompt sanitization
- tool allow/deny augmentation
- operator notifications
- post-tool auditing
- workflow triggers

Without this, every policy becomes bespoke code or fragile prompt wording.

### Recommended implementation
Create `core/hooks.py` with:
- a hook registry
- event names for session/tool/permission lifecycle
- optional blocking hooks for permission-sensitive events
- fire-and-forget hooks for observability-only events

Suggested first events:
- `session_start`
- `pre_tool_use`
- `post_tool_use`
- `tool_error`
- `permission_request`
- `session_end`

This is one of the cleanest ways to make dolOS customizable without turning `core/agent.py` into a monolith.

---

## Gap 13 — Durable Transcripts + Resumable Task Output

### What Claude Code has
Conversation transcripts and task outputs are durable runtime artifacts:
- sessions can be resumed
- subagent sidechains persist
- task output is written to disk incrementally
- long-running work survives UI interruption or process restart more gracefully

### What dolOS has
dolOS has:
- episodic memory
- semantic memory
- telemetry

But it does **not** yet have a first-class exact transcript store or resumable task-output persistence for long-running agent work.

### Why it matters
Vector memory is not a substitute for:
- exact replay
- crash recovery
- debugging a broken turn loop
- resuming interrupted work
- inspecting precise tool-call chronology

As soon as dolOS gets plan mode, subagents, or durable tasks, transcript persistence becomes foundational.

### Recommended implementation
Add:
- `storage/transcripts.py` for append-only session transcripts
- `storage/task_output.py` for incremental task output files
- a small `/resume` command/API for listing and resuming recent sessions

Persist:
- user messages
- assistant messages
- tool invocations/results
- background task status changes

This should happen before or alongside any real coordinator/subagent rollout.

---

## Gap 14 — Session Bootstrap + Cache-Stable Prompt Assembly

### What Claude Code has
The harness separates:
- startup/system-init context
- memoized system context
- memoized user/project context
- volatile per-turn state

This keeps prompts more stable and makes context assembly inspectable.

### What dolOS has
`Agent.process_message()` assembles one large system prompt per turn from:
- tool descriptions
- SOUL.md
- LESSONS.md
- summary text
- episodic retrieval
- semantic retrieval

This works, but it mixes stable and volatile prompt sections into one block every turn.

### Why it matters
As the system grows, prompt assembly becomes an architectural concern:
- harder to inspect
- harder to reason about cache behavior
- harder to debug prompt regressions
- easier to accidentally inject noisy or redundant context

### Recommended implementation
Split prompt construction into explicit layers:
1. `system_bootstrap` — stable environment and capability info
2. `identity` — SOUL / behavior policy
3. `persistent_memory` — lessons + static project docs
4. `session_memory` — summary + session KV
5. `retrieved_context` — episodic + semantic recall
6. `tool_descriptions` — filtered, permission-aware, context-aware

Also emit prompt-shape telemetry:
- prompt section sizes
- total chars/tokens by section
- hash/fingerprint of the stable sections

This is not just optimization; it is a maintainability upgrade.

---

## Gap 15 — Working Memory Files, Not Just Vector Memory

### What Claude Code has
Multiple memory horizons:
- persistent project/user memory files
- session memory file
- exact current-session notes
- relevant memory file selection

### What dolOS has
dolOS already indexes static files like `USER.md` and `MEMORY.md`, and it has vector memory plus lessons. What it still lacks is a **human-editable working-memory layer** for active operational context.

### Why it matters
Some information is better stored as editable text artifacts than embeddings:
- current task focus
- project runbook
- known gotchas
- active constraints
- temporary working assumptions

This is especially useful in local-first systems where the operator wants transparent control.

### Recommended implementation
Add a small file-based memory layer under `data/`:
- `CURRENT_TASK.md`
- `RUNBOOK.md`
- `KNOWN_ISSUES.md`
- `SESSION_NOTES/<session_id>.md`

Then:
- index these into semantic memory
- allow direct read/write through explicit commands or guarded skills
- inject the most relevant ones into prompt assembly

This complements Gap 5's session K/V store rather than replacing it.

---

## Additional Priority Matrix

| Gap | Impact | Effort | Priority |
|-----|--------|--------|----------|
| **Gap 10: Operator Commands** | 🟡 Reliability + UX | 🟢 1 day | **Soon** |
| **Gap 11: Parallel Read-Only Tools** | 🟡 Speed + Scalability | 🟡 1-2 days | **Soon** |
| **Gap 12: Hook Framework** | 🔴 Architecture + Policy | 🟡 2-3 days | **Next sprint** |
| **Gap 13: Durable Transcripts / Resume** | 🔴 Reliability + Debuggability | 🟡 2-4 days | **Next sprint** |
| **Gap 14: Prompt Assembly Layers** | 🟡 Maintainability + Prompt Quality | 🟡 2 days | **Next sprint** |
| **Gap 15: Working Memory Files** | 🟡 Capability + Operator Control | 🟡 1-2 days | **After session K/V** |

---

## Phased Parallel Execution Plan

> **For any agent or developer picking up this work:** this section defines how all 15 gaps map to parallel-safe work packages, which gaps share files (and therefore must be sequential), and what must be verified at each phase boundary before the next phase begins.

---

### Dependency Graph

The following blocking relationships determine phase ordering:

```
Gap 7  (Bash Validator)     → blocks nothing — isolated new file
Gap 9  (Token Budget)       → blocks nothing — only llm.py
Gap 5  (Session K/V)        → blocks nothing — only new memory/ file
Gap 10 (Operator Commands)  → blocks nothing — new core/commands.py

Gap 2  (Tool Contracts)     ← must land before Gaps 1, 4, 11, 8
Gap 14 (Prompt Layers)      ← must land before Gap 3 (plan mode)
Gap 13 (Durable Transcripts)← pairs with Gap 10 (/resume command)

Gap 1  (Permission Layer)   ← needs Gap 2 (is_read_only metadata)
Gap 4  (Dynamic Routing)    ← needs Gap 2 (schema extension)
Gap 11 (Parallel Tools)     ← needs Gap 2 (concurrency_safe metadata)
Gap 12 (Hook Framework)     ← needs Gap 1 (permission events)

Gap 3  (Plan Mode)          ← needs Gap 1 + Gap 14
Gap 8  (MCP Server)         ← needs Gap 1 + Gap 2

Gap 6  (Subagents)          ← needs Gap 1 + Gap 3 + Gap 12 + Gap 13
```

---

### Phase 1 — Safety & Foundation (Fully Parallelizable)

> ✅ **All 4 agents can run simultaneously. Zero shared file edits.**

| Agent | Gaps | Files Touched | Duration |
|-------|------|--------------|----------|
| **Agent A** | Gap 7 — Bash Validator | `skills/bash_validator.py` (new), `skills/sandbox.py` | 0.5 day |
| **Agent B** | Gap 9 — Token Budget | `core/llm.py`, `core/agent.py`, `core/config.py` | 1 day |
| **Agent C** | Gap 5 — Session K/V | `memory/session_kv.py` (new), `skills/local/session_memory.py` (new) | 1 day |
| **Agent D** | Gap 10 — Operator Commands | `core/commands.py` (new), `channels/terminal.py`, `api/routes/chat.py` | 1 day |

**Agent A — Bash Validator (Gap 7):**
- Create `skills/bash_validator.py` with `DANGEROUS_PATTERNS` list and `validate_bash_command()` function
- Wire into `SandboxExecutor.execute_command()` as a pre-flight check — return error dict without executing if unsafe
- Tests: `tests/skills/test_bash_validator.py`
- Acceptance: `validate_bash_command("rm -rf /")` → `is_safe=False`; all 221 existing tests still pass

**Agent B — Token Budget (Gap 9):**
- Capture `response.usage` in `LLMGateway.generate()` and emit a `TELEMETRY` event with token counts
- Add `session_token_tracker: dict[str, int]` to `Agent` (cumulative tokens per session)
- Log `WARNING` when within 20% of model context window (add `MODEL_CONTEXT_WINDOW` to `config.py`)
- Update summarization trigger: fire on turn count OR token threshold
- Tests: `tests/core/test_token_budget.py`

**Agent C — Session K/V Store (Gap 5):**
- Create `memory/session_kv.py` with `SessionKVStore` (per-session JSON-backed K/V store)
- Expose `set_session_memory(key, value)` and `get_session_memory(key)` as `@skill` entries in `skills/local/session_memory.py`
- **Do NOT wire into `agent.py` prompt yet** — that happens in Phase 2 (Agent E)
- Tests: `tests/memory/test_session_kv.py`

**Agent D — Operator Commands (Gap 10):**
- Create `core/commands.py` with a `CommandRouter` class handling `/`-prefixed input
- Register: `/memory search <q>`, `/memory stats`, `/compact`, `/skills list`, `/doctor`
- Wire into `channels/terminal.py` and `api/routes/chat.py`: intercept `/` prefix before `agent.process_message()`
- Tests: `tests/core/test_commands.py`
- Acceptance: `/skills list` returns registered skill names without making an LLM call

---

### Phase 2 — Architecture Foundation

> ⚠️ **Can start while Phase 1 is still running — Agents E and F touch different files from Phase 1 agents and from each other.**

| Agent | Gaps | Files Touched | Duration |
|-------|------|--------------|----------|
| **Agent E** | Gap 2 + Gap 14 — Tool Contracts + Prompt Layers | `skills/registry.py`, `core/prompt_builder.py` (new), `core/agent.py`, `skills/local/*.py` | 2 days |
| **Agent F** | Gap 13 — Durable Transcripts | `storage/transcripts.py` (new), `storage/__init__.py` (new), `core/agent.py`, `core/commands.py` | 2 days |

> ⚠️ **Both Agent E and Agent F touch `core/agent.py`.** They must work on separate branches and merge sequentially at the Phase 2 checkpoint.

**Agent E — Tool Contracts + Prompt Layers (Gaps 2 + 14):**

*Gap 2:*
- Extend `SkillRegistration` in `skills/registry.py` with: `is_read_only: bool = True`, `concurrency_safe: bool = True`, `description_fn: Callable[[], str] | None = None`
- Update `@skill` decorator to accept `read_only=`, `concurrency_safe=`, `description_fn=` kwargs
- Update all existing skill registrations in `skills/local/` to declare correct metadata

*Gap 14:*
- Create `core/prompt_builder.py` with a `PromptBuilder` class accepting named sections: `system_bootstrap`, `identity`, `persistent_memory`, `session_memory`, `retrieved_context`, `tool_descriptions`
- Move all inline prompt construction out of `agent.py` into `PromptBuilder.build()`
- Emit telemetry with per-section character counts
- Tests: `tests/core/test_prompt_builder.py`

**Agent F — Durable Transcripts (Gap 13):**
- Create `storage/transcripts.py` with `TranscriptStore` — append-only JSONL per session under `data/transcripts/<session_id>.jsonl`
- Records: user messages, assistant messages, tool_call + tool_result pairs, background task events
- Update `agent.py` to call `TranscriptStore.append()` at each turn stage (non-blocking)
- Add `/resume [session_id]` handler to `core/commands.py` (Agent D's file — coordinate on merge)
- Tests: `tests/storage/test_transcripts.py`

---

### Phase 3 — Permission Architecture + Hook Framework

> ⚠️ **Requires Phase 2 (Agent E) merged first.** Gaps 1, 4, 11 depend on `is_read_only` and `concurrency_safe` metadata from Gap 2.
> ✅ **Agents G, H, and I are independent of each other within this phase.**

| Agent | Gaps | Files Touched | Duration |
|-------|------|--------------|----------|
| **Agent G** | Gap 1 + Gap 4 + Gap 11 — Permissions + Routing + Parallel | `skills/permissions.py` (new), `skills/registry.py`, `core/agent.py` | 2-3 days |
| **Agent H** | Gap 12 — Hook Framework | `core/hooks.py` (new), `core/agent.py` | 2 days |
| **Agent I** | Gap 15 — Working Memory Files | `memory/static_loader.py`, `skills/local/session_notes.py` (new) | 1-2 days |

> ⚠️ **Agent G and Agent H both touch `core/agent.py`.** Work on separate branches and merge sequentially at Phase 3 checkpoint.

**Agent G — Permission Layer + Dynamic Routing + Parallel Tools (Gaps 1 + 4 + 11):**

*Gap 1:*
- Create `skills/permissions.py` with `PermissionPolicy(deny_names, deny_prefixes, allow_only)` dataclass
- Add `filter_schemas(schemas)` method
- Wire `permission_policy: PermissionPolicy | None` into `Agent.__init__`
- Apply `filter_schemas()` before building tool list each turn
- Default: no restrictions (existing behavior unchanged)

*Gap 4:*
- Add `SkillRegistry.get_relevant_schemas(query, max_tools=10)` — keyword intersection scoring
- Replace `get_all_schemas()` calls in `agent.py` with `get_relevant_schemas(message)`
- Threshold: only activates when registry has >10 tools

*Gap 11:*
- Partition pending tool calls into `concurrent_batch` (read-only + concurrency_safe=True) vs `serial_queue`
- Run `concurrent_batch` with `asyncio.gather()`, then `serial_queue` sequentially
- Tests: `tests/skills/test_permissions.py`, `tests/skills/test_routing.py`, `tests/core/test_parallel_tools.py`

**Agent H — Hook Framework (Gap 12):**
- Create `core/hooks.py` with `HookRegistry` supporting blocking hooks (`pre_tool_use`, `permission_request`) and fire-and-forget hooks (`post_tool_use`, `tool_error`, `session_start`, `session_end`)
- Wire into `agent.py`: fire `session_start` at top of `process_message()`, `pre_tool_use` before each tool call (can veto), `post_tool_use` and `tool_error` after results
- Tests: `tests/core/test_hooks.py`
- Acceptance: A `pre_tool_use` hook raising `PermissionError` blocks tool execution without crashing the session

**Agent I — Working Memory Files (Gap 15):**
- Extend `memory/static_loader.py` to discover and inject `data/CURRENT_TASK.md`, `data/RUNBOOK.md`, `data/KNOWN_ISSUES.md`
- Create `data/SESSION_NOTES/` directory
- Add `write_session_note(content)` and `read_session_notes()` skills in `skills/local/session_notes.py`
- Tests: `tests/memory/test_working_memory.py`

---

### Phase 4 — Plan Mode, MCP Server, Subagents

> ⚠️ **All require Phase 3 fully merged before starting.**
> ✅ **Agents J and K can run in parallel. Agent L is gated on both J and K being stable.**

| Agent | Gaps | Requires | Duration |
|-------|------|---------|----------|
| **Agent J** | Gap 3 — Plan Mode | Gaps 1, 12, 14 | 2-3 days |
| **Agent K** | Gap 8 — MCP Server | Gaps 1, 2 | 1-2 days |
| **Agent L** | Gap 6 — Subagents | Gaps 1, 3, 12, 13 | 2-3 weeks |

**Agent J — Plan Mode (Gap 3):**
- Create `core/plan_mode.py` with `PlanModeSession` tracking per-session plan state
- In plan mode: apply read-only `PermissionPolicy`; inject plan-mode instructions via `PromptBuilder`
- Add `/plan` (enter plan mode) and `/approve` (exit and execute) to operator command layer
- Fire `pre_tool_use` hook to block mutating tools when in plan mode
- Tests: `tests/core/test_plan_mode.py`

**Agent K — MCP Server (Gap 8):**
- Create `tools/mcp_server.py` using the `mcp` Python SDK
- Expose `list_tools()` from the skill registry (permission-filtered) and `call_tool()` routing to `SkillExecutor`
- Add `--mcp` startup flag to `main.py`
- Tests: `tests/tools/test_mcp_server.py`

**Agent L — Subagents / Coordinator (Gap 6):**
- Phase A: Create `spawn_subagent(task, tools)` skill — recursive `Agent.process_message()` with scoped `PermissionPolicy`
- Create `core/task_tracker.py` with `TaskTracker` — in-memory task store (ID, status, result)
- Expose `task_create`, `task_update`, `task_list` skills
- Phase B (later): Background subagents, task dependency chains
- Tests: `tests/core/test_subagent.py`

---

### Parallel Execution Timeline

```
Week 1
├── Agent A: Gap 7  — Bash Validator        ████░░░░░░░░░░░░░░░░░░░░░░░░
├── Agent B: Gap 9  — Token Budget          ████████░░░░░░░░░░░░░░░░░░░░
├── Agent C: Gap 5  — Session K/V           ████████░░░░░░░░░░░░░░░░░░░░
└── Agent D: Gap 10 — Operator Commands     ████████░░░░░░░░░░░░░░░░░░░░

Week 1-2                    [Phase 1 checkpoint]
├── Agent E: Gap 2+14 — Contracts+Prompt    ░░░░░░░░████████████░░░░░░░░
└── Agent F: Gap 13  — Transcripts          ░░░░░░░░████████████░░░░░░░░

Week 2-3                    [Phase 2 checkpoint]
├── Agent G: Gap 1+4+11 — Perm+Route+Par   ░░░░░░░░░░░░░░░░░░░░████████
├── Agent H: Gap 12 — Hook Framework        ░░░░░░░░░░░░░░░░░░░░████████
└── Agent I: Gap 15 — Working Memory        ░░░░░░░░░░░░░░░░░░░░████░░░░

Week 3-4                    [Phase 3 checkpoint]
├── Agent J: Gap 3  — Plan Mode             ░░░░░░░░░░░░░░░░░░░░░░░░████
├── Agent K: Gap 8  — MCP Server            ░░░░░░░░░░░░░░░░░░░░░░░░████
└── Agent L: Gap 6  — Subagents             ░░░░░░░░░░░░░░░░░░░░░░░░░░▒▒  (starts after J+K)
```

---

### Integration Checkpoints

| Checkpoint | Gate Condition | What to verify |
|-----------|---------------|----------------|
| **Phase 1 → 2** | All 4 Phase 1 PRs merged | All existing tests pass; no regressions in agent loop |
| **Phase 2 → 3** | Agent E merged | `PromptBuilder` unit tests pass; 6 named prompt sections confirmed; `is_read_only` metadata on all skills |
| **Phase 3 → 4** | Agents G + H merged | `PermissionPolicy(allow_only={"read_file"})` blocks `run_command` from being sent to LLM; hook veto test passes |
| **Phase 4-J done** | Plan mode e2e test | `/plan` → agent proposes plan → `/approve` → executes correctly |
| **Phase 4-K done** | MCP integration test | External MCP client can call dolOS skills via stdio transport |
| **Phase 4-L done** | Subagent isolation test | Subagent with `allow_only={"read_file"}` cannot invoke `run_command` |

---

### File Conflict Map

Files touched by more than one agent — these require sequential merging or branch coordination:

| File | Agents | Resolution |
|------|--------|-----------|
| `core/agent.py` | B (P1), E (P2), F (P2), G (P3), H (P3), J (P4) | Sequential per phase — one agent per phase merges first |
| `skills/registry.py` | E (P2), G (P3) | Sequential — G starts after E merges |
| `core/commands.py` | D (P1, new), F (P2 — adds /resume), J (P4 — adds /plan, /approve) | D creates file; F and J add to it in later phases |

**Rule:** Phase 1 has zero shared files — fully safe to parallelize all 4 agents simultaneously.

---

### Directive File Structure

One directive per work package under `directives/`:

```
directives/
├── 010_bash_validator.md          # Gap 7   — Agent A
├── 011_token_budget.md            # Gap 9   — Agent B
├── 012_session_kv.md              # Gap 5   — Agent C
├── 013_operator_commands.md       # Gap 10  — Agent D
├── 020_tool_contracts_prompt.md   # Gap 2+14 — Agent E
├── 021_durable_transcripts.md     # Gap 13  — Agent F
├── 030_permission_routing.md      # Gap 1+4+11 — Agent G
├── 031_hook_framework.md          # Gap 12  — Agent H
├── 032_working_memory.md          # Gap 15  — Agent I
├── 040_plan_mode.md               # Gap 3   — Agent J
├── 041_mcp_server.md              # Gap 8   — Agent K
└── 050_subagents.md               # Gap 6   — Agent L
```

Each directive should include: goal, acceptance criteria, files to create/modify, test file locations, and which phase/checkpoint gates it.

---

*Phasing plan appended: 2026-04-06 | Based on dependency graph analysis of all 15 gaps*

---

*Phase 5 gaps appended: 2026-04-06 | Sourced from hermes-agent (nousresearch/hermes-agent) analysis*

---

## Phase 5 — hermes-agent Gaps

> **Source:** Cross-reference against [nousresearch/hermes-agent](https://github.com/nousresearch/hermes-agent).
> **Context:** All 15 Claude Code gaps (Phases 1–4) are complete. These are the next-highest-value gaps identified from hermes-agent's architecture.

---

## Gap H1 — Structured Context Compression (4-Phase Iterative Summarization)

### What hermes-agent has
A `context_compressor.py` with a 4-phase strategy that fires when the context window fills:

1. **Tool output pruning** — old tool results replaced with short `[tool result omitted]` placeholders. No LLM call, zero cost.
2. **Head/tail protection** — system prompt + first exchange frozen; recent ~20K tokens kept verbatim.
3. **Structured summarization** — middle turns collapsed via a fixed template: `Goal / Progress / Decisions / Files Changed / Next Steps`.
4. **Iterative merge** — subsequent compressions merge new progress into the *existing* summary rather than starting fresh. Coherence is preserved across multiple compression cycles.

Token budget: summary capped at 20% of compressed content, max 12K tokens. Injects budget-pressure warnings as the iteration limit approaches.

### What dolOS has
Gap 9 added token budget monitoring and a summarization trigger in `core/agent.py`. The trigger fires but the actual summarization is a single-pass LLM call with no structured template and no iterative merge — each compression starts from scratch.

### Why it matters
Long-running sessions (30+ turns) lose coherence without iterative merging. The structured template ensures the LLM always knows the current goal and which files are in play, even after multiple compression cycles.

### Recommended implementation
Create `core/context_compressor.py`:

```python
SUMMARY_TEMPLATE = """
## Session Summary
**Goal:** {goal}
**Progress:** {progress}
**Decisions:** {decisions}
**Files Changed:** {files}
**Next Steps:** {next_steps}
"""

class ContextCompressor:
    async def compress(
        self,
        messages: list[dict],
        prior_summary: str | None,
        llm: LLMGateway,
        head_tokens: int = 4000,
        tail_tokens: int = 20000,
    ) -> tuple[list[dict], str]:
        # Phase 1: prune tool outputs older than tail window
        # Phase 2: split messages into head / middle / tail
        # Phase 3: summarize middle with template
        # Phase 4: if prior_summary exists, merge rather than replace
        ...
```

Wire into `Agent.process_message()`: after each turn, check token count. If above threshold, call `ContextCompressor.compress()` and replace `self._history` with the compressed version + injected summary block.

**Effort:** 2–3 days. Reuses existing token tracking from Gap 9 and `LLMGateway`.

**Files:** `core/context_compressor.py` (new), `core/agent.py` (wire in), `tests/core/test_context_compressor.py` (new)

---

## Gap H4 — Context Reference `@` Syntax (CLI Inline Injection)

### What hermes-agent has
Users can inject external content inline in CLI prompts using `@` prefixes:

| Syntax | Injects |
|--------|---------|
| `@file:path/to/file.py` | Full file contents |
| `@file:main.py:10-25` | Line range only |
| `@folder:path/` | All files in directory (with size guard) |
| `@diff` | Current `git diff` (unstaged) |
| `@staged` | `git diff --staged` |
| `@git:N` | Last N commits (`git log -N -p`) |
| `@url:https://...` | Web page content (extracted) |

Features: tab completion for discovery, binary file detection, sensitive path blocking (SSH keys, `.env`), soft limit at 25% context (warning), hard limit at 50% (expansion blocked).

### What dolOS has
The terminal channel (`channels/terminal.py`) accepts plain text prompts. Users have to describe files verbally or ask the agent to read them as a tool call — an extra round-trip that costs a full LLM turn.

### Why it matters
`@diff` before a code review question, or `@file:core/agent.py` before asking "why does this loop hang?" — these are the daily interactions that make a local CLI agent feel native rather than clunky. Eliminates an entire class of unnecessary tool-call round-trips.

### Recommended implementation

Create `core/context_refs.py`:

```python
import re, subprocess
from pathlib import Path

REF_PATTERN = re.compile(r'@(file|folder|diff|staged|git|url):?([^\s]*)')

BLOCKED_PATTERNS = ['.ssh/', '.env', 'credentials', 'id_rsa', 'id_ed25519']
SOFT_LIMIT_RATIO = 0.25   # warn
HARD_LIMIT_RATIO = 0.50   # block expansion

def expand_refs(prompt: str, context_window: int = 128_000) -> str:
    """Replace @ref tokens with inline content. Mutates nothing — pure expansion."""
    hard_limit = int(context_window * HARD_LIMIT_RATIO)
    injected_chars = 0
    ...
```

Wire into `channels/terminal.py`: before passing the prompt to `CommandRouter` / `agent.process_message()`, run `expand_refs(raw_input)`. The agent sees a fully-expanded prompt; no code changes needed in `Agent` itself.

Tab completion: hook into `prompt_toolkit`'s `Completer` to suggest `@file:` paths when the user types `@`.

**Effort:** 2–3 days (expansion logic + prompt_toolkit completer + sensitive path guard + tests).

**Files:** `core/context_refs.py` (new), `channels/terminal.py` (wire in), `tests/core/test_context_refs.py` (new)

---

## Gap H5 — OpenAI-Compatible Chat Completions Endpoint

### What hermes-agent has
An HTTP API server exposing `POST /v1/chat/completions` (stateless, full history in body) and `POST /v1/responses` (stateful, server-side session). Any frontend speaking the OpenAI wire format — Open WebUI, LibreChat, ChatBox, SillyTavern — can connect with no custom client.

### What dolOS has
`POST /chat` with `{session_id: str, message: str}` → `{content: str}`. This is dolOS's own format. No OpenAI-format consumer can connect without a custom adapter.

### Why the custom format exists
dolOS was built as a Python/FastAPI simplification of the OpenClaw (Node.js) architecture. OpenClaw itself uses a custom WebSocket + device-pairing protocol, so there was no OpenAI-compat to inherit. The `{session_id, message}` design was a deliberate simplification — not an intentional deviation from OpenAI format.

### Why the retrofit is smaller than it looks
dolOS already uses **LiteLLM** internally, which means it already speaks OpenAI format *outbound* to the LLM. The gap is only on the *inbound* side. `agent.process_message()` already handles the hard part.

### Design decisions to resolve before implementing

| Decision | Options |
|----------|---------|
| **Session ID** | Derive from `user` field in request body; or generate per-request (stateless); or accept as `X-Session-Id` header |
| **Message history** | Pass full `messages` array to agent (true stateless mode) vs. extract only last user message (rely on dolOS session memory) |
| **Streaming** | SSE `data: {"choices":[{"delta":{"content":"..."}}]}` — most frontends require it; LiteLLM already supports stream mode |

### Recommended implementation

Add `api/routes/v1_chat.py`:

```python
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import json, uuid, time

v1_router = APIRouter(prefix="/v1")

class ChatCompletionRequest(BaseModel):
    model: str = "dolOS"
    messages: list[dict]           # [{role, content}, ...]
    stream: bool = False
    user: str | None = None        # used as session_id if provided

@v1_router.post("/chat/completions")
async def chat_completions(data: ChatCompletionRequest, request: Request):
    agent = request.app.state.agent
    session_id = data.user or uuid.uuid4().hex
    user_message = next(
        (m["content"] for m in reversed(data.messages) if m["role"] == "user"),
        ""
    )
    reply = await agent.process_message(session_id=session_id, message=user_message)

    payload = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
    }
    return payload
```

Mount in `main.py`: `app.include_router(v1_router)`.

Streaming can be added as a follow-up by surfacing LiteLLM's `stream=True` mode through an `AsyncGenerator` and returning `StreamingResponse`.

**Effort:** 2–3 hours without streaming; ~1 day with SSE streaming.

**Files:** `api/routes/v1_chat.py` (new), `main.py` (mount router), `tests/api/test_v1_chat.py` (new)

---

### Phase 5 — Dependency Graph & Sequencing

All three Phase 5 gaps are **independent** — they touch different files and can be implemented in parallel.

| Gap | Agent | Touches | Parallel-safe? |
|-----|-------|---------|---------------|
| H1 — Context Compression | M | `core/context_compressor.py` (new), `core/agent.py` | Yes (new file + isolated agent.py section) |
| H4 — `@` Context Refs | N | `core/context_refs.py` (new), `channels/terminal.py` | Yes (new file + terminal only) |
| H5 — OpenAI API Compat | O | `api/routes/v1_chat.py` (new), `main.py` | Yes (new route file) |

**Phase 5 gate:** All three can merge in any order. No integration checkpoint required between them.

### File Conflict Map (Phase 5)

| File | Agents | Resolution |
|------|--------|-----------|
| `core/agent.py` | M (H1) | Isolated: only `compress()` call added to turn loop |
| `main.py` | O (H5) | Isolated: only `app.include_router(v1_router)` added |

### Directive File Structure (Phase 5)

```
directives/
├── 050_context_compression.md     # Gap H1  — Agent M
├── 051_context_refs.md            # Gap H4  — Agent N
└── 052_openai_compat_api.md       # Gap H5  — Agent O
```
