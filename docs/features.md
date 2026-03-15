Agreed, observability is the right priority. Here is everything, structured so you can feed it directly as a prompt or task list.

---

**Observability & dashboard (your priority, do this first)**

Structured logging with a unique trace ID per request that flows through every layer: gateway → agent → memory → tool call → response. Without a shared trace ID you cannot correlate what happened across components. Use Python `structlog` with JSON output.

OpenTelemetry for spans. Every LLM call, every Qdrant query, every heartbeat task gets a span with duration, token count, model used, and success/failure. This feeds into Tempo or Jaeger locally.

Dashboard panels you actually want: live agent activity feed (what is it doing right now), LLM call timeline (which model, how long, tokens in/out, cost estimate), memory hit rate over time, fallback frequency (how often Ollama fails and escalates to Claude/GPT), heartbeat health (did the 30-min job actually run, what did it find), channel message volume by source, skill invocation frequency, Qdrant collection size growth over time, and error rate by component.

Real-time WebSocket feed from the agent's internal event bus pushed to the dashboard. Every decision the agent makes emits an event: "chose local model", "memory miss, querying Qdrant", "skill invoked: X", "falling back to Claude". This is what makes the dashboard feel alive rather than just a metrics board.

---

**Reliability layer**

Asyncio task queue with per-channel concurrency limits. Telegram, Discord, heartbeat, and API requests should each have a dedicated queue with a max concurrent worker count. Prevents a flood of Telegram messages from starving the heartbeat.

Circuit breaker on every external dependency: Ollama, Qdrant, Gmail API, Google Calendar, Claude API. Use `pybreaker` or implement a simple state machine. When Ollama goes down, the circuit opens immediately instead of every request hanging until timeout.

Dead man's switch for the heartbeat. A simple endpoint that gets hit every 30 minutes. If it goes more than 45 minutes without a hit, push a Telegram alert. You will thank yourself for this at 11pm when the scheduler silently died.

Explicit retry policy per integration. Ollama gets 2 retries with 500ms backoff. Cloud LLMs get 3 retries with exponential backoff. Gmail API gets 1 retry. Different dependencies have different failure modes, treat them differently.

Health check endpoint (`/health/deep`) that tests every dependency: Qdrant ping, Ollama model load status, Gmail token validity, NFS mount reachability. Not just "is the process running" but "can it actually do its job."

---

**Context and memory improvements**

Conversation summarizer that runs automatically when a thread exceeds 60% of the model's context window. Summarize older turns into a compressed block, keep the last N turns verbatim. Store the summary back into Qdrant as a special memory type so it is retrievable.

Memory importance scoring. Not all memories are equal. When writing to Qdrant, score each memory on a scale (recency, access frequency, explicit user signal like "remember this"). Use the score to break ties when top-k results are close in similarity. Decay old low-scored memories over time.

Episodic vs semantic memory separation. Right now everything goes into one collection. Episodic (what happened in conversation X on date Y) and semantic (user prefers terminal, working on GPU Autopilot) should be separate collections with different retrieval strategies.

---

**Skills and tools**

Pydantic schemas for every skill input and output. The agent validates before calling, catches mismatches before they cause silent failures downstream.

Skill execution sandbox. Generated skills run in a subprocess with restricted filesystem access, no network unless explicitly declared in the skill manifest, and a hard timeout. Think of it like a controlled burn: the agent can create fire, but in a firepit.

Tool call audit log. Every tool invocation, its inputs, outputs, duration, and whether it succeeded gets written to a structured log. Feeds into the dashboard. Non-negotiable for an agent that can write its own skills.

---

**Security hardening**

Secret rotation support. Right now API keys are static in `.env`. Add a mechanism to reload secrets without restarting the process, either via a file watcher on `.env` or a local Vault instance (HashiCorp Vault runs fine on Proxmox).

Input sanitization on all channel adapters before anything reaches the agent. Telegram messages, Discord messages, and API payloads should be stripped of prompt injection attempts before hitting LiteLLM. A simple blocklist of injection patterns plus a max token pre-check goes a long way.

Per-user rate limiting on the Telegram and Discord adapters, not just global rate limiting. Even with an allowlist of user IDs, a single user rapidly firing messages should not be able to monopolize the agent.

---

**Operational quality of life**

Graceful shutdown handler. On SIGTERM, drain in-flight tasks, flush logs, checkpoint current memory state to disk, then exit. Right now if systemd restarts the process mid-conversation, that context is gone.

Configuration hot reload. Settings like heartbeat interval, active hours, and model temperature should be changeable without a restart. A `SIGHUP` handler that re-reads `settings.yaml` is enough.

Cost tracking. Every Claude/GPT-4 call has a dollar cost. Track tokens in/out per model per day, estimate spend, and surface it on the dashboard. With Ollama as primary this stays low, but fallback storms can get expensive fast.

---

Feed all of the above as a single structured prompt to the agent with your existing README as context. Frame it as: "retrofit these capabilities into the existing architecture, propose file locations for each new component, and flag any conflicts with existing modules." It will give you a solid implementation plan without having to redesign from scratch.

Yes, absolutely. Grafana is overkill here and adds operational overhead you do not need. Building observability directly into your existing FastAPI + React dashboard is the cleaner approach and fits your local-first philosophy perfectly.

Here is the architecture for a homegrown observability layer that lives entirely inside your existing stack:

**The core pattern**

Every agent action emits an event to an internal event bus (a simple asyncio `Queue`). A collector consumes that queue and writes to three places: SQLite for persistence, an in-memory ring buffer for the live feed, and a WebSocket broadcaster for the dashboard. No external dependencies.

```
Agent action → EventBus (asyncio Queue)
                    ↓
              EventCollector
              ↙      ↓       ↘
         SQLite   RingBuffer  WebSocket
         (persist) (live feed) (dashboard push)
```

**What to store in SQLite**

Three tables cover everything:

`events` table: timestamp, trace_id, event_type, component, payload (JSON), duration_ms, success bool. This is your audit log and the source for all charts.

`metrics` table: timestamp, metric_name, value, labels (JSON). Aggregated counts and gauges written every 60 seconds by a background task. LLM call count, token totals, memory hit rate, cost estimate, fallback count.

`traces` table: trace_id, started_at, completed_at, channel, model_used, total_tokens, memory_hits, tools_invoked (JSON array), success bool. One row per end-to-end request. This is what powers the request timeline view.

SQLite is sufficient here. You are not at Postgres scale. A week of dense agent activity is maybe 50MB. Add a simple retention job that deletes rows older than 30 days.

**Event types to instrument**

```python
class EventType(str, Enum):
    # LLM
    LLM_CALL_START = "llm.call.start"
    LLM_CALL_END = "llm.call.end"
    LLM_FALLBACK = "llm.fallback"
    
    # Memory
    MEMORY_QUERY = "memory.query"
    MEMORY_HIT = "memory.hit"
    MEMORY_MISS = "memory.miss"
    MEMORY_WRITE = "memory.write"
    
    # Tools / Skills
    TOOL_INVOKE = "tool.invoke"
    TOOL_COMPLETE = "tool.complete"
    TOOL_ERROR = "tool.error"
    SKILL_INVOKE = "skill.invoke"
    
    # Heartbeat
    HEARTBEAT_START = "heartbeat.start"
    HEARTBEAT_COMPLETE = "heartbeat.complete"
    HEARTBEAT_MISS = "heartbeat.miss"
    
    # Channels
    MESSAGE_RECEIVED = "channel.message.received"
    MESSAGE_SENT = "channel.message.sent"
    
    # System
    FALLBACK_TRIGGERED = "system.fallback"
    CIRCUIT_OPEN = "system.circuit.open"
    ERROR = "system.error"
```

**The event emitter (drops into every component)**

```python
# core/telemetry.py
import asyncio, time, uuid
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Event:
    event_type: str
    component: str
    trace_id: str
    payload: dict = field(default_factory=dict)
    duration_ms: float = 0
    success: bool = True
    timestamp: float = field(default_factory=time.time)

class EventBus:
    _queue: asyncio.Queue = asyncio.Queue()
    
    @classmethod
    async def emit(cls, event: Event):
        await cls._queue.put(event)
    
    @classmethod
    def emit_sync(cls, event: Event):
        cls._queue.put_nowait(event)

# Usage anywhere in the codebase:
await EventBus.emit(Event(
    event_type=EventType.LLM_CALL_END,
    component="agent.llm",
    trace_id=ctx.trace_id,
    payload={"model": "ollama/qwen2.5:32b", "tokens_in": 420, "tokens_out": 183},
    duration_ms=2340,
    success=True
))
```

**Dashboard panels to build in React**

Live activity feed: a scrolling list of events from the WebSocket, newest at top, color-coded by event type. Teal for memory ops, blue for LLM calls, amber for tools, red for errors. Each row shows timestamp, trace ID (clickable), component, and a short human-readable summary generated from the event payload.

Request trace view: click any trace ID and get a waterfall timeline for that entire request. Gateway received → memory query (Xms) → LLM call (Xms, model Y, Z tokens) → tool invoke → response sent. Similar to what Jaeger shows but yours, in your dashboard.

LLM panel: calls per hour bar chart, model distribution pie (Ollama vs Claude vs GPT-4), average latency per model, token usage over time, estimated daily cost (hardcode $/token rates per model, calculate locally).

Memory panel: hit rate over time line chart, Qdrant collection size, top retrieved memory chunks by frequency, write volume per hour.

Heartbeat health: a simple grid of the last 48 heartbeat slots (30-min intervals during active hours). Green = ran and found nothing, amber = ran and sent alert, red = missed. At a glance you know if the scheduler is healthy.

Error log: last 100 errors with full payload, component, and trace ID. Filterable by component. No digging through log files.

System health strip at the top of the dashboard: Ollama status (responding / degraded / down), Qdrant (connected / disconnected), Gmail token (valid / expired), NFS mount (reachable / unreachable), circuit breaker states. Updates every 10 seconds via WebSocket.

**WebSocket push from FastAPI**

```python
# api/websocket.py - add alongside existing handler
class ObservabilityBroadcaster:
    clients: set[WebSocket] = set()
    
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)
        # send last 100 events from ring buffer on connect
        await ws.send_json({"type": "init", "events": ring_buffer.last(100)})
    
    async def broadcast(self, event: Event):
        dead = set()
        for client in self.clients:
            try:
                await client.send_json(event.__dict__)
            except:
                dead.add(client)
        self.clients -= dead
    
    # Collector calls this for every event coming off the EventBus queue
```

**What this gives you that Grafana cannot**

The trace waterfall tied to a conversation thread is something Grafana cannot do without significant configuration. You can click a Telegram message in the activity feed and see the exact chain of everything the agent did to respond to it: which memories it retrieved, which model it called, how long each step took, what the fallback chain looked like. That is genuinely more useful than a generic metrics dashboard.

You also get the ability to add domain-specific panels that make sense for your agent specifically, like a "skill invocation heatmap" showing which auto-generated skills are actually being used, or a "memory staleness" view showing chunks that have not been retrieved in 30 days and are candidates for pruning.

The total additional dependencies for all of this: `aiosqlite` for async SQLite access, nothing else. Everything else is already in your stack.