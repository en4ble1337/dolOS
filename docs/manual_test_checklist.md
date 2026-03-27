# dolOS: Granular Manual UAT Checklist

Use this checklist to verify that all user-facing components and complex agent behaviors are functioning properly.

## 1. Environment & URLs
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **Interactive API Docs (Swagger)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Telemetry Health**: [http://localhost:8000/api/health/deep](http://localhost:8000/api/health/deep)
- **Frontend Dashboard**: [http://localhost:5173](http://localhost:5173) (if running via `npm run dev`)

---

## 2. Dashboard: Home View (Dashboard Overview)
*Navigate to [http://localhost:5173](http://localhost:5173)*

- [ ] **System Status Strip (Top)**:
    - [ ] `Ollama`: Green indicator (Connected)
    - [ ] `Qdrant`: Green indicator (Connected)
    - [ ] `Memory`: Shows non-zero record count
- [ ] **Heartbeat Grid**:
    - [ ] 48-slot grid is visible.
    - [ ] Slots turn green as background tasks (Health/Reflection) execute.
    - [ ] Tooltip on grid reveals task name and "Success: True".
- [ ] **Live Telemetry Feed**:
    - [ ] New events (`CHAT_MESSAGE`, `TOOL_INVOKE`) appear instantly without page refresh.
    - [ ] Events show correct `trace_id` and `timestamp`.
- [ ] **Metrics Panels**:
    - [ ] `LLM Latency`: Line chart shows data points.
    - [ ] `Memory Growth`: Bar chart showing Episodic vs Semantic storage.

## 3. Dashboard: Trace Waterfall
*Click on a Trace ID in the Activity Feed*

- [ ] **Waterfall Rendering**:
    - [ ] Shows nested blocks: `AGENT_LOOP` -> `TOOL_EXECUTION` -> `TOOL_COMPLETE`.
    - [ ] Timing bars accurately represent duration of each step.
- [ ] **Payload Inspection**:
    - [ ] Clicking a block reveals the JSON payload (e.g., the exact command sent to `run_command`).

---

## 4. Channel Integrations
- [ ] **Telegram Bot**:
    - [ ] Send `/start` -> Receives welcome message.
    - [ ] Send `What is your soul?` -> Responds with personality from `SOUL.md`.
    - [ ] Verify `CHAT_MESSAGE` event appears on Dashboard.
- [ ] **Discord Bot**:
    - [ ] Bot shows as "Online" in the sidebar.
    - [ ] Responds to @mention in a public channel.
- [ ] **Terminal Channel**:
    - [ ] Run `python main.py` and interact directly.
    - [ ] Verify `[THINK]` blocks are visible (if model supports it).

---

## 5. High-Stakes Autonomous Behavior
- [ ] **Learning Loop (Lessons Learned)**:
    1. Tell agent: "Always use emojis when responding to me."
    2. Verification turn: "Hello!"
    3. **Pass**: Response contains emoji.
    4. Check `data/LESSONS.md`: Verify a new entry was created.
    5. Restart agent and verify the preference still holds.
- [ ] **Self-Correction (Tool Fallback)**:
    1. Request: "Run a command to check disk space using a tool you DON'T have called 'check_disk'".
    2. **Pass**: Agent recognizes it lacks 'check_disk' and calls `run_command(command="df -h")` instead.

---

## 6. Reliability & Performance
- [ ] **SIGTERM Shutdown**:
    - [ ] Send `Ctrl+C` to the process.
    - [ ] Verify "Shutting down Agent Backend..." and "Clean teardown" logs appear.
- [ ] **Concurrency Test**:
    - [ ] Send messages via Telegram and Terminal simultaneously.
    - [ ] Verify both are processed without blocking each other (concurrency check).
