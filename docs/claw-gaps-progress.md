# dolOS claw-gaps: Implementation Progress

> Branch: `feature/claw-gaps`
> Last updated: 2026-04-06
> Source plan: `docs/claw-gap-analysis.md`

---

## How to use this document

Any agent or developer resuming this work should:
1. Read this file to find the current phase and which gaps remain.
2. Check the dependency graph in `docs/claw-gap-analysis.md` → "Phased Parallel Execution Plan" before starting a new phase.
3. Mark gaps as ✅ **Done** here when merged, and add the merge commit SHA.
4. Do not start Phase N+1 until all blocking gaps from Phase N are merged (see Integration Checkpoints below).

---

## Phase 1 — Safety & Foundation

> All 4 gaps are fully parallelizable (zero shared file edits).
> **Phase 1 → 2 gate:** All existing tests pass + no regressions in agent loop.

| Gap | Status | Files | Notes |
|-----|--------|-------|-------|
| **Gap 7 — Bash Validator** | ✅ Done | `skills/bash_validator.py`, `skills/sandbox.py` | Pre-flight check in `SandboxExecutor.execute_command()`. Tests: `tests/skills/test_bash_validator.py` |
| **Gap 9 — Token Budget** | ✅ Done | `core/config.py`, `core/llm.py`, `core/agent.py` | `model_context_window` config; token usage telemetry; session tracker; summarization fires on turn count OR token threshold. Tests: `tests/core/test_token_budget.py` |
| **Gap 5 — Session K/V Store** | ✅ Done | `memory/session_kv.py`, `skills/local/session_memory.py` | Per-session JSON-backed K/V. Skills: `set_session_memory`, `get_session_memory`. NOT yet wired into agent.py prompt (Phase 2). Tests: `tests/memory/test_session_kv.py` |
| **Gap 10 — Operator Commands** | ✅ Done | `core/commands.py`, `channels/terminal.py`, `api/routes/chat.py` | `/memory search`, `/memory stats`, `/compact`, `/skills list`, `/doctor` commands. Intercept `/` prefix before `agent.process_message()`. Tests: `tests/core/test_commands.py` |

---

## Phase 2 — Architecture Foundation

> **Gate:** Phase 1 fully merged. Agent E and Agent F both touch `core/agent.py` — merge sequentially.

| Gap | Status | Files | Notes |
|-----|--------|-------|-------|
| **Gap 2 — Typed Tool Contracts** | ⬜ Pending | `skills/registry.py`, `skills/local/*.py` | Extend `SkillRegistration` with `is_read_only`, `concurrency_safe`, `description_fn`. Update `@skill` decorator. |
| **Gap 14 — Prompt Assembly Layers** | ⬜ Pending | `core/prompt_builder.py` (new), `core/agent.py` | `PromptBuilder` with 6 named sections. Move inline prompt assembly out of `agent.py`. Wire in Session K/V from Gap 5. |
| **Gap 13 — Durable Transcripts** | ⬜ Pending | `storage/transcripts.py` (new), `storage/__init__.py` (new), `core/agent.py`, `core/commands.py` | Append-only JSONL transcripts. Wire `/resume` command. |

> **Phase 2 → 3 gate:** `PromptBuilder` unit tests pass; 6 named prompt sections confirmed; `is_read_only` metadata on all skills.

---

## Phase 3 — Permission Architecture + Hook Framework

> **Gate:** Phase 2 (Gap 2 / Agent E) merged. Agents G, H, I are independent within this phase, but G and H both touch `core/agent.py` — merge sequentially.

| Gap | Status | Files | Notes |
|-----|--------|-------|-------|
| **Gap 1 — Permission Layer** | ⬜ Pending | `skills/permissions.py` (new), `skills/registry.py`, `core/agent.py` | `PermissionPolicy` dataclass with `deny_names`, `deny_prefixes`, `allow_only`. `filter_schemas()` wired into Agent. |
| **Gap 4 — Dynamic Tool Routing** | ⬜ Pending | `skills/registry.py`, `core/agent.py` | `get_relevant_schemas(query, max_tools=10)` — keyword scoring. Activates only when registry > 10 tools. |
| **Gap 11 — Parallel Read-Only Tools** | ⬜ Pending | `core/agent.py` | Partition tool calls into `concurrent_batch` (read-only + concurrency_safe) vs `serial_queue`. Use `asyncio.gather()`. |
| **Gap 12 — Hook Framework** | ⬜ Pending | `core/hooks.py` (new), `core/agent.py` | `HookRegistry` with blocking hooks (`pre_tool_use`, `permission_request`) and fire-and-forget hooks. |
| **Gap 15 — Working Memory Files** | ⬜ Pending | `memory/static_loader.py`, `skills/local/session_notes.py` (new) | Inject `CURRENT_TASK.md`, `RUNBOOK.md`, `KNOWN_ISSUES.md`. `SESSION_NOTES/<id>.md`. |

> **Phase 3 → 4 gate:** `PermissionPolicy(allow_only={"read_file"})` blocks `run_command`; hook veto test passes.

---

## Phase 4 — Plan Mode, MCP Server, Subagents

> **Gate:** Phase 3 fully merged. Agent J and K can run in parallel. Agent L requires J+K stable.

| Gap | Status | Files | Notes |
|-----|--------|-------|-------|
| **Gap 3 — Plan Mode** | ⬜ Pending | `core/plan_mode.py` (new), `core/agent.py`, `core/commands.py` | `/plan` enters plan mode (read-only policy). `/approve` exits and executes. |
| **Gap 8 — MCP Server** | ⬜ Pending | `tools/mcp_server.py` (new), `main.py` | Expose skill registry over MCP stdio. `--mcp` startup flag. |
| **Gap 6 — Subagents** | ⬜ Pending | `skills/local/subagent.py` (new), `core/task_tracker.py` (new) | Phase A: `spawn_subagent(task, tools)`. Phase B: `TaskTracker` with `task_create/update/list`. |

---

## Integration Checkpoints (from plan)

| Checkpoint | Gate Condition | What to verify |
|-----------|---------------|----------------|
| **Phase 1 → 2** | All 4 Phase 1 PRs merged | All existing tests pass; no regressions in agent loop |
| **Phase 2 → 3** | Agent E (Gap 2+14) merged | `PromptBuilder` unit tests pass; 6 named prompt sections confirmed; `is_read_only` metadata on all skills |
| **Phase 3 → 4** | Agents G + H merged | `PermissionPolicy(allow_only={"read_file"})` blocks `run_command` from being sent to LLM; hook veto test passes |
| **Phase 4-J done** | Plan mode e2e test | `/plan` → agent proposes plan → `/approve` → executes correctly |
| **Phase 4-K done** | MCP integration test | External MCP client can call dolOS skills via stdio transport |
| **Phase 4-L done** | Subagent isolation test | Subagent with `allow_only={"read_file"}` cannot invoke `run_command` |

---

## File Conflict Map (read before parallel work)

| File | Agents / Phases | Resolution |
|------|----------------|-----------|
| `core/agent.py` | B(P1), E(P2), F(P2), G(P3), H(P3), J(P4) | Sequential per phase — one agent per phase merges first |
| `skills/registry.py` | E(P2), G(P3) | Sequential — G starts after E merges |
| `core/commands.py` | D(P1), F(P2), J(P4) | Sequential — each phase adds new commands only |
