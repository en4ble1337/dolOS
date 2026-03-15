# Directive 010: Observability Dashboard (Frontend)

## Objective
Build a React-based Observability Dashboard to visualize the telemetry emitted by the backend (Events, Metrics, and Traces). This will grant us absolute x-ray vision into the internal state of the agent, making future features much easier to build and debug.

## Context
The entire backend for this is finished and running. The `EventBus` works, events are flowing to `agent.db` via `aiosqlite`, and the metrics are being aggregated by `EventCollector`. We also have WebSocket and REST endpoints configured under `api/routes/observability.py`.

## Acceptance Criteria
- [ ] Initialize a new React Frontend in the `ui/` directory using Vite + React + TypeScript + TailwindCSS.
- [ ] Implement a WebSocket client that connects to `ws://localhost:8000/api/events/live` and handles real-time payloads.
- [ ] Build a **Live Activity Feed** component that streams the last N events sequentially.
- [ ] Build a **Heartbeat Grid** to visualize background task health.
- [ ] Build an **LLM metrics** chart panel (Tokens over time, response times) pulling from REST or live events using Recharts or Chart.js.
- [ ] Build a **Memory Stats** panel mapping database hits vs misses.
- [ ] Build a **Request Waterfall Visualization** that chunks events via `trace_id` so we can see an end-to-end user request traversing the system.
- [ ] Style the dashboard to be heavily matrix/terminal inspired or a very clean dark mode, matching a local-first AI aesthetic.

## Development Methodology
- Write an implementation plan inside `docs/plans/`.
- Ensure everything is strictly typed.
- Remember the frontend is entirely decoupled from the Python code and relies exclusively on `/api` routes!
