# Environment Docs Cleanup Implementation Plan

**Directive:** ad hoc user request
**Date:** 2026-03-27
**Goal:** Align environment-variable documentation and example files with the actual runtime settings, while removing dead or misleading variables from the default setup path.
**Architecture Notes:** The runtime config contract is defined by `core/config.py` via `Settings`. This task does not change Python behavior; it only updates docs and env templates to match the existing contract. `DATA_DIR` is a legacy name that currently feeds `VectorStore(location=...)`, so it may be either a filesystem path or an HTTP Qdrant URL.

---

### Task 1: Capture the current config contract

**Files:**
- Read: `core/config.py`
- Read: `main.py`
- Read: `memory/vector_store.py`

**Step 1:** Inspect the declared settings
- File: `core/config.py`
- Action: Read `Settings` fields and defaults.
- Run: `Get-Content core/config.py`
- Expected: A complete list of supported env vars and defaults.

**Step 2:** Confirm how memory location is consumed
- File: `main.py`
- File: `memory/vector_store.py`
- Action: Verify whether `DATA_DIR` is treated strictly as a path or as a generic Qdrant location.
- Run: `Get-Content main.py`
- Run: `Get-Content memory/vector_store.py`
- Expected: `VectorStore(location=settings.data_dir)` and support for either local paths or `http...` locations.

---

### Task 2: Update user-facing env docs and examples

**Files:**
- Modify: `README.md`
- Modify: `QUICKSTART.md`
- Modify: `.env.example`
- Modify: `deploy/.env.example`

**Step 1:** Update the README env section
- File: `README.md`
- Action: Replace stale env guidance with a minimal local-first `.env` example, optional channel/alert vars, memory toggles, and a note that cloud fallback keys are intentionally omitted by default.
- Run: `rg -n "Configuration \\(`.env`\\)|cp .*\\.env\\.example" README.md`
- Expected: The README points to the correct env example and no longer mentions dead config.

**Step 2:** Update Quick Start setup steps
- File: `QUICKSTART.md`
- Action: Remove the `API_TOKEN` instruction and the nonexistent `config/settings.yaml.example` step; keep the flow focused on `.env`.
- Run: `rg -n "API_TOKEN|settings.yaml.example" QUICKSTART.md`
- Expected: No matches.

**Step 3:** Replace stale env templates
- File: `.env.example`
- File: `deploy/.env.example`
- Action: Make both examples reflect `core/config.py` and the local-first defaults.
- Run: `rg -n "API_TOKEN|GOOGLE_|RCLONE_|QDRANT_HOST|QDRANT_PORT|OLLAMA_BASE_URL|TELEGRAM_USER_ID|DISCORD_CHANNEL_ID" .env.example deploy/.env.example`
- Expected: No matches.

---

### Task 3: Verify the cleanup

**Files:**
- Read: `README.md`
- Read: `QUICKSTART.md`
- Read: `.env.example`
- Read: `deploy/.env.example`

**Step 1:** Verify dead env references are gone
- Action: Search for removed variables and missing file paths.
- Run: `rg -n "API_TOKEN|settings.yaml.example|your_secure_api_token_here" README.md QUICKSTART.md .env.example deploy/.env.example`
- Expected: No matches.

**Step 2:** Run targeted config tests for regression confidence
- Action: Confirm the config contract still behaves as expected.
- Run: `pytest tests/core/test_config.py -v`
- Expected: All tests pass.
