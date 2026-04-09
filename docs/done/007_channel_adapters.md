# Directive 007: Channel Adapters (Terminal & FastAPI)

## Objective
Build the entry points for interacting with the agent. This directive focuses on standardizing how text gets into the `Agent.process_message` method and how responses get routed back, starting with a Local Terminal interface and a generic REST controller.

## File Ownership & Boundaries (CRITICAL FOR PARALLEL EXECUTION)
**Allowed to modify/create:**
- `channels/terminal.py` (Interactive CLI chat loop using `prompt_toolkit` and `rich`)
- `api/routes/chat.py` (FastAPI REST endpoints for chatting)
- `tests/channels/test_terminal.py`
- `tests/api/test_chat.py`

**OFF-LIMITS (Do NOT modify):**
- `core/*`
- `memory/*`

## Acceptance Criteria
- [x] Implement a generic `Channel` interface/protocol.
- [x] Implement `TerminalChannel` in `channels/terminal.py` using `rich` for markdown formatting and `prompt_toolkit` for async input.
- [x] Create `api/routes/chat.py` with an async REST endpoint (`POST /chat`) that accepts a session ID and text.
- [x] Both channels must emit `MESSAGE_RECEIVED` and `MESSAGE_SENT` telemetry events.
- [x] Wrap incoming channel requests with `set_trace_id()` to ensure tracing starts at the absolute edge of the system.
- [x] Write integration and unit tests for the channel abstractions.

## Development Methodology Reminder
Follow the rules in `AGENTS.md` strictly:
1. Write an implementation plan first (`docs/plans/...`).
2. TDD Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
3. Verify via running the tests. Do not guess.
