# Feature Difficulty Assessment for `dolOS`

> [!NOTE]
> This is a **read-only assessment**, not an implementation plan. It evaluates every feature group from [features.md](file:///c:/Users/Bart/Documents/AI/Projects/my-local-agent/docs/features.md) against the current state of the codebase.

## Current State of the Codebase

The project is an **early-stage scaffold**. The directory structure and configuration examples are well-designed, but most modules contain only empty `__init__.py` stubs:

| Module | Status | Notes |
|--------|--------|-------|
| `core/` | Empty `__init__.py` | No `agent.py`, `llm.py`, `config.py` yet |
| `memory/` | Empty directory | No `vector_store.py`, `search.py` |
| `channels/` | Empty `__init__.py` | No adapters implemented |
| `heartbeat/` | Empty stubs | `integrations/` exists but empty |
| `tools/` | Empty `__init__.py` | No MCP client or tool interfaces |
| `skills/` | Empty stubs | `local/` directory exists but empty |
| `api/` | Empty stubs | `routes/` exists but empty |
| `ui/` | **Empty directory** | No React app at all |

README roadmap shows Phase 1 (core + memory + terminal) as checked, but the actual implementation files don't exist in the repo. This means **all features are net-new work built on a greenfield scaffold**.

---

## 1. Observability & Dashboard (Your Priority)

### Difficulty: 🟡 Medium (with significant scope)

The observability feature doc is the most detailed section, and fortunately, it's also the most **self-contained**. It doesn't depend heavily on other features being complete first.

### What's involved

| Sub-feature | Effort | New Dependency | Notes |
|-------------|--------|---------------|-------|
| `EventBus` (asyncio Queue) | **Low** | None | ~50 lines. Pure Python, no deps |
| `Event` dataclass + `EventType` enum | **Low** | None | Already spec'd in the doc |
| SQLite persistence (3 tables) | **Low** | `aiosqlite` | Well-defined schema in the doc |
| In-memory ring buffer | **Low** | None | Simple deque-based, ~30 lines |
| `EventCollector` background task | **Low-Med** | None | Consumes queue, writes to 3 sinks |
| WebSocket broadcaster | **Low** | None | FastAPI WS already in deps |
| Trace ID propagation | **Medium** | None | Needs a context pattern across all layers |
| Metrics aggregation task (60s) | **Low** | None | Background asyncio task |
| SQLite retention cleanup | **Low** | None | Simple DELETE WHERE older than 30d |
| React dashboard (6+ panels) | **High** | React setup | `ui/` is empty. Full frontend build |
| Live activity feed (WS) | **Medium** | None | Client-side WS consumption |
| Request trace waterfall view | **High** | None | Custom timeline visualization |
| LLM panel (charts) | **Medium** | Charting lib | Bar charts, pie, line charts |
| Memory panel | **Medium** | Charting lib | Hit rate over time, collection size |
| Heartbeat health grid | **Low-Med** | None | 48-slot grid, color-coded |
| Error log panel | **Low** | None | Filterable table |
| System health strip | **Low-Med** | None | Status indicators, 10s refresh |

### Key Observations

1. **Backend observability is straightforward.** The `EventBus` → `EventCollector` → SQLite/RingBuffer/WebSocket pattern is clean, well-spec'd, and only requires `aiosqlite` as a new dependency. A solid engineer could build the backend telemetry layer in **2-3 days**.

2. **The hard part is the dashboard.** The `ui/` directory is completely empty. You need to:
   - Bootstrap a React app (Vite recommended)
   - Build 6+ dashboard panels with charting (Recharts/Chart.js)
   - Implement WebSocket client state management
   - Build the trace waterfall (custom component, most complex piece)
   - This is easily **5-8 days** of frontend work.

3. **Trace ID propagation is the most architecturally impactful piece.** Every request needs a `trace_id` that flows through gateway → agent → memory → tool → response. This requires a context variable pattern (Python `contextvars`) that must be wired into every component. Since those components don't exist yet, this is actually easier now than it would be later (you can bake it in from the start).

4. **Only 1 new pip dependency**: `aiosqlite`. Everything else (`asyncio.Queue`, `websockets`, `fastapi`) is already in the stack.

### Recommendation

> [!TIP]
> **Start observability now, before building other features.** Since the core modules are empty stubs, you can design the trace ID pattern into every component from day one. Retrofitting trace IDs into existing code is much harder than building them in.

**Suggested phasing:**
1. **Phase A (1-2 days):** `EventBus`, `Event`, `EventType`, `EventCollector`, SQLite tables, ring buffer
2. **Phase B (1 day):** WebSocket broadcaster, FastAPI endpoint, metrics aggregation task
3. **Phase C (5-8 days):** React dashboard with all panels
4. **Phase D (1 day):** Trace ID propagation pattern (ready to wire into components as they're built)

---

## 2. Reliability Layer

### Difficulty: 🟡 Medium

| Sub-feature | Effort | Notes |
|-------------|--------|-------|
| Asyncio task queue with per-channel concurrency | **Medium** | Needs channel adapters to exist first |
| Circuit breaker (all external deps) | **Low-Med** | `pybreaker` or ~100-line state machine |
| Dead man's switch for heartbeat | **Low** | Simple timer + Telegram alert |
| Per-integration retry policies | **Low-Med** | Decorator pattern, ~100 lines |
| Deep health check (`/health/deep`) | **Medium** | Needs each integration to exist to probe it |

### Key Observation
Most reliability features are **decorators/wrappers around integrations that don't exist yet**. Circuit breakers, retry policies, and health checks only make sense once Ollama, Qdrant, Gmail, and Calendar integrations are actually implemented. The task queue depends on channel adapters existing.

> [!IMPORTANT]
> Build reliability patterns as **reusable utilities** now, then wire them in as you build each integration. Don't try to build the full reliability layer in isolation.

---

## 3. Context & Memory Improvements

### Difficulty: 🔴 Hard

| Sub-feature | Effort | Notes |
|-------------|--------|-------|
| Conversation summarizer (auto at 60% context) | **High** | Needs working LLM + token counting + memory write-back |
| Memory importance scoring | **Medium** | Scoring function + Qdrant payload filtering |
| Episodic vs semantic separation | **Medium-High** | Separate Qdrant collections, different retrieval strategies |

### Key Observation
These features depend on having a **working memory system first** (`memory/` is currently empty). They also require a functioning LLM integration for the summarizer. This is Phase 2+ work.

---

## 4. Skills & Tools Improvements

### Difficulty: 🟡 Medium

| Sub-feature | Effort | Notes |
|-------------|--------|-------|
| Pydantic schemas for skill I/O | **Low** | Natural fit, Pydantic is already a dep |
| Skill execution sandbox (subprocess) | **Medium-High** | Subprocess isolation, fs restrictions, timeouts |
| Tool call audit log | **Low** | Feeds into observability EventBus |

### Key Observation
The audit log is essentially **free if you build observability first** since it's just another `TOOL_INVOKE` / `TOOL_COMPLETE` event. The sandbox is the hardest piece here (process isolation on Windows is trickier than Linux).

---

## 5. Security Hardening

### Difficulty: 🟡 Medium

| Sub-feature | Effort | Notes |
|-------------|--------|-------|
| Secret rotation (file watcher or Vault) | **Low-Med** | `watchfiles` for .env reload, or HashiCorp Vault |
| Input sanitization (prompt injection) | **Medium** | Blocklist + token pre-check on all channel adapters |
| Per-user rate limiting | **Low** | Token bucket per user ID, ~50 lines |

### Key Observation
These are incremental features that layer on top of channel adapters and config management. Not urgent for MVP, but the input sanitization should be considered early.

---

## 6. Operational Quality of Life

### Difficulty: 🟢 Easy-Medium

| Sub-feature | Effort | Notes |
|-------------|--------|-------|
| Graceful shutdown (SIGTERM handler) | **Low** | `signal.signal` + drain tasks + flush |
| Config hot reload (SIGHUP) | **Low** | Re-read `settings.yaml`, update in-memory |
| Cost tracking ($/token per model) | **Low** | Token counts from LLM calls × hardcoded rates |

### Key Observation
These are all small, self-contained features. Cost tracking feeds naturally into the observability dashboard. Graceful shutdown is ~30 lines. These can be sprinkled in as you go.

---

## Summary: Difficulty Ranking

| Feature Group | Difficulty | Est. Effort | Dependencies |
|--------------|-----------|-------------|--------------|
| **Observability backend** | 🟢 Easy-Medium | 2-3 days | `aiosqlite` only |
| **Observability dashboard** | 🔴 Hard | 5-8 days | React setup, charting lib |
| **Operational QoL** | 🟢 Easy | 1-2 days | None |
| **Reliability layer** | 🟡 Medium | 3-4 days | Core integrations must exist |
| **Security hardening** | 🟡 Medium | 2-3 days | Channel adapters must exist |
| **Skills & Tools** | 🟡 Medium | 3-4 days | Skills system must exist |
| **Context & Memory** | 🔴 Hard | 5-7 days | Full memory system + LLM |

### What I'd Recommend for Observability

The observability **backend** is the best bang-for-buck starting point:
- It's **self-contained** (only needs `aiosqlite`)
- It establishes **patterns used everywhere** (EventBus, trace IDs)
- Building it first means every future component automatically emits telemetry
- The dashboard can come later once there are actual events to visualize

The trace waterfall view described in the doc is genuinely more useful than Grafana for an agent like this; the doc is right about that. But it's also the most complex frontend component to build.

> [!CAUTION]
> Since the core modules are all stubs, the effective total effort to get observability **meaningfully working** (not just the telemetry plumbing, but actual events flowing through a real agent) also requires building the core agent loop, LLM integration, and at least one channel adapter. Factor that into your planning.
