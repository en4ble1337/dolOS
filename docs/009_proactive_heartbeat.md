# Directive 009: Proactive Heartbeat System

## Objective
Implement `APScheduler` to give the agent proactive autonomy. The agent shouldn't just wait for user input; it should wake up on a timer, assess its state, summarize recent memory, and perform background health checks.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `core/heartbeat.py` (APScheduler wrapper and standard jobs)
- `tests/core/test_heartbeat.py`

**OFF-LIMITS (Do NOT modify):**
- `api/*`
- `memory/*`
- `core/agent.py`
- `core/llm.py`

## Acceptance Criteria
- [x] Initialize `AsyncIOScheduler` from `apscheduler` in `core/heartbeat.py`.
- [x] Implement a registration mechanism for recurring background tasks.
- [x] Create a "Self-Reflection" heartbeat task that periodically triggers the agent to summarize older episodic memories.
- [x] Create a "Health Check" task that pings dependencies (Qdrant, Ollama) and logs their status.
- [x] Emit `HEARTBEAT_START` and `HEARTBEAT_COMPLETE` telemetry events for every job execution.
- [x] Add tests verifying that scheduler registration and task execution work as expected.

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
