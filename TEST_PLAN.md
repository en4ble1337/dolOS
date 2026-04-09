# dolOS: Comprehensive Test Plan

This document defines the verification strategy for `dolOS` across three tiers of testing to ensure reliability, autonomy, and correctness.

## 1. Automated Unit/Integration Tier (CI/CD)
**Tool**: `pytest`
**Frequency**: Every commit

- **Core Orchestrator**: Verify the `Agent` loop, tool-call parsing, and message processing with mocks.
- **Memory Systems**: Test `vector_store` (Qdrant), `episodic` retrieval, `semantic` persistence, and `LessonExtractor` logic.
- **Skills Registry**: Verify `@skill` registration, schema generation, and sandbox execution (timeouts/truncation).
- **Telemetry**: Ensure `EventBus` emits events to SQLite and WebSockets correctly.
- **Channel Adapters**: Unit tests for Telegram/Discord payload transformation.

## 2. Autonomous System Tier (Headless)
**Tool**: `pytest` + `TerminalChannel`
**Frequency**: Nightly / Pre-Release

- **Multi-Step Tool Chaining**: Verification that the agent can execute "Find file -> Read file -> Summarize" in a single session.
- **Self-Correction (Learning)**: A test where the agent is instructed to use a non-existent tool, fails, and must decide to use `run_command` or `run_code` instead.
- **Episodic Continuity**: Verify that a fact provided in Turn 1 is correctly used as context in Turn 5 after multiple background tasks have run.

## 3. Manual User Acceptance Tier (UAT)
**Document**: `docs/manual_test_checklist.md`
**Frequency**: Major releases / Periodic "Vibe Checks"

- **Dashboard Visuals**: Verify all 6+ panels (Memory, Heartbeat, Trace Waterfall) render live data correctly.
- **Channel VIBE**: Test "personality" and response quality on real Telegram/Discord clients.
- **Proactive Alerts**: Trigger a "Manually Induced Crash" to verify systemd restart and Telegram alerting.

## 4. Feature Coverage Matrix

| Feature | Automated Coverage | Manual Check |
|---------|-------------------|--------------|
| Tool Execution | `tests/skills/` | Prompt 1-2 |
| Lessons Learned | `tests/memory/` | Prompt 5-6 |
| Dashboard | N/A (UI) | Checklist Q1-Q6 |
| Channel Sync | `tests/channels/` | Real Chat |
| Memory Recall | `tests/memory/` | Prompt 5 |

## 5. Ubuntu 24.04 Manual Smoke Pass
**Target**: First real-system validation on Ubuntu 24.04 before broader operator testing
**Applies to**: Local Ollama + local Qdrant + `systemd` deployment path

### Preconditions
- Ubuntu 24.04 host with Python 3.11+ and the repo checked out under `/opt/dolOS` or an equivalent persistent path.
- Ollama running locally with the configured primary model already pulled.
- Qdrant reachable using the configured local storage or service settings.
- `.env` populated for the target host.
- Virtualenv dependencies installed.

### Boot Checks
1. Start the app interactively once:
   ```bash
   .venv/bin/python main.py
   ```
   Expected:
   - FastAPI starts without import/runtime errors.
   - Transcript index initialization logs complete.
   - No immediate crash from terminal/channel setup.

2. In a second shell, confirm the health endpoint:
   ```bash
   curl -s http://127.0.0.1:8000/health
   ```
   Expected:
   - HTTP `200`
   - healthy JSON response

### Functional Smoke Script
Use one fresh session and verify the following in order.

1. Basic reply path
   - Send: a plain question that needs no tools.
   - Expected:
   - assistant returns a normal answer
   - user and assistant turns are appended to `data/transcripts/<session>.jsonl`

2. Tool execution path
   - Send: a request that clearly requires `run_command`, for example asking for the current directory contents.
   - Expected:
   - the agent uses a tool instead of only describing what to do
   - transcript contains `tool_call` and `tool_result` entries
   - no tool loop hangs

3. Semantic extraction path
   - Send: a durable fact, for example `Remember that my deployment target is Ubuntu 24.04 and my repo lives in /opt/dolOS.`
   - Expected:
   - the turn completes normally
   - a later query in a new session can recall the fact from semantic memory

4. Summarization / compression path
   - Drive the session long enough to trigger summarization or token-budget compression.
   - Expected:
   - logs show summarization and/or `[COMPRESSOR]` entries
   - subsequent replies still preserve recent context
   - no missing-`trace_id` crash during compression

5. `USER.md` refresh path
   - Complete 10 full user/assistant turns in one session with stable preferences or work-context details.
   - Expected:
   - `data/USER.md` updates after the 10th completed turn
   - the updated profile is re-indexed without duplicate stale chunks
   - later prompts reflect the new profile instructions

6. Transcript search path
   - Ask for something that should invoke `search_transcripts`, or call it through the memory skill surface.
   - Suggested query: a unique phrase from an earlier turn in the smoke session.
   - Expected:
   - results come from the SQLite FTS transcript index
   - matches include the correct session snippets

### systemd Checks
1. Install and start the service:
   ```bash
   sudo cp deploy/dolOS.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now dolOS
   ```
   Expected:
   - service reaches `active (running)`

2. Inspect logs:
   ```bash
   journalctl -u dolOS -n 100 --no-pager
   ```
   Expected:
   - clean startup
   - no repeated restart loop

3. Verify restart behavior:
   ```bash
   sudo systemctl kill dolOS
   sleep 5
   systemctl status dolOS --no-pager
   ```
   Expected:
   - `systemd` restarts the service automatically
   - the app returns to healthy state

### Smoke Exit Criteria
- Interactive startup passes.
- Health endpoint responds.
- Tool execution works on the live host.
- Semantic recall works across sessions.
- Summarization/compression completes without crashing.
- `USER.md` updates after 10 turns.
- Transcript search returns expected results.
- `systemd` restart behavior is confirmed.
