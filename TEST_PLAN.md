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
