# Skill Validation, Self-Healing & MCP Integration — Change Log

**Date:** 2026-03-28
**Branch:** main

This document records every file added or modified during the skill validation, self-healing loop, and MCP server integration implementation.

---

## Summary of Changes

### What was implemented

1. **Skill validation before write** (`create_skill`) — LLM-generated code is validated with `ast.parse()` and an AST walk before touching disk, preventing broken Python from ever being saved.
2. **Self-healing skill loop** — when a generated skill fails at runtime, the agent receives an actionable error with instructions to call `fix_skill` → read broken code → `create_skill` with corrected version.
3. **MCP server integration** — fetch, Brave web search, and Playwright browser automation are wired in out of the box via `config/mcp_servers.yaml` and `tools/mcp_loader.py`.
4. **Peer review fixes** — 1 CRITICAL and 4 WARNING issues identified by a second review agent were corrected before merge.

---

## New Files

### `config/mcp_servers.yaml`
Defines the three default MCP servers. Each entry specifies `command`, `args`, optional `env` vars (using `${VAR}` syntax resolved from `.env`), and `optional: true` for servers that should skip gracefully when prerequisites are absent.

| Server | Package | Requires | Tools registered |
|--------|---------|----------|-----------------|
| `fetch` | `@modelcontextprotocol/server-fetch` | Node.js only | `fetch(url)` |
| `brave-search` | `@modelcontextprotocol/server-brave-search` | `BRAVE_API_KEY` in `.env` | `brave_web_search`, `brave_local_search` |
| `playwright` | `@playwright/mcp` | Node.js + `npx playwright install chromium` | `browser_navigate`, `browser_click`, `browser_fill`, `browser_screenshot`, `browser_get_text`, and others |

### `tools/mcp_loader.py`
`MCPServerManager` class — the bridge between the YAML config and the running agent.

Key behaviour:
- Loads `config/mcp_servers.yaml` at startup
- Expands `${VAR}` references from the process environment
- For each enabled server: resolves env vars → creates `StdioServerParameters` → calls `MCPClientWrapper.connect()` → calls `bind_tools()` to register all tools into `SkillRegistry`
- `optional: true` servers are silently skipped on missing env vars or failed connections
- Non-optional servers log a warning on failure but do not crash the agent
- `close_all()` gracefully disconnects all servers on shutdown
- Lazy `from mcp import StdioServerParameters` inside `connect_all()` — if `mcp` package is absent, returns 0 and logs a warning instead of crashing the import

### `tests/tools/test_mcp_loader.py`
11 tests covering: `_expand_env` resolution and non-resolution, missing YAML file, empty YAML, no `mcpServers` key, `enabled: false` skip, optional server with missing env var (skip), optional server with env var set (connect), optional server connection failure (skip), non-optional connection failure (warning logged), `mcp` package not installed (returns 0), `close_all` calls close on all clients.

---

## Modified Files

### `skills/local/meta.py`

**Additions:**
- `import ast` added
- Pre-write validation in `create_skill`:
  1. `ast.parse(file_content)` — catches `SyntaxError` before touching disk; returns the error message to the LLM
  2. AST walk for `ast.AsyncFunctionDef` named `handler` — catches wrong function name (e.g. sync `def handler` or misnamed function); returns "must contain async def handler"
  3. Import try/except with cleanup — if `spec.loader.exec_module()` raises (bad imports, module-level runtime error), the file is deleted and evicted from `sys.modules`
- New `fix_skill` skill:
  - Reads and returns the full source of any file in `skills/local/generated/`
  - Returns an error if the skill is not found (built-in skills are not readable this way)
  - Used by the agent as the first step in the self-correction loop

**Before (no validation):**
```python
skill_file.write_text(file_content, encoding="utf-8")
spec.loader.exec_module(module)
return f"Skill '{name}' created..."
```

**After (three-layer validation):**
```python
# Layer 1: syntax
try:
    tree = ast.parse(file_content)
except SyntaxError as e:
    return f"Error: Syntax error in generated code — {e}"

# Layer 2: structure
if not any(isinstance(n, ast.AsyncFunctionDef) and n.name == "handler" for n in ast.walk(tree)):
    return "Error: Generated code must contain an async function named 'handler'."

# Layer 3: import
skill_file.write_text(file_content, encoding="utf-8")
try:
    spec.loader.exec_module(module)
except Exception as e:
    skill_file.unlink(missing_ok=True)
    sys.modules.pop(module_name, None)
    return f"Error: Skill code failed to import — {e}"
```

### `skills/executor.py`

**Additions:**
- `from pathlib import Path`
- `_GENERATED_DIR = Path(__file__).parent / "local" / "generated"`
- Self-correction hint appended to **both** `Exception` and `asyncio.TimeoutError` error messages when the failing skill has a file in `_GENERATED_DIR`:
  ```
  — This is a generated skill. Call fix_skill(name='X') to retrieve its current source,
    then call create_skill(name='X', ...) with corrected code to replace it.
  ```

### `tools/mcp_client.py`

**Fix (closure bug):** `make_tool_func` now accepts `tool_description` as an explicit parameter instead of closing over the loop variable `tool`. Previously all tool wrappers would have `__doc__` pointing to the last tool's description after the loop completed.

**Before:**
```python
def make_tool_func(tool_name: str) -> Any:
    async def mcp_tool_wrapper(**kwargs):
        ...
    mcp_tool_wrapper.__doc__ = tool.description  # ← loop variable, late binding
    return mcp_tool_wrapper
func = make_tool_func(tool.name)
```

**After:**
```python
def make_tool_func(tool_name: str, tool_description: str | None) -> Any:
    async def mcp_tool_wrapper(**kwargs):
        ...
    mcp_tool_wrapper.__doc__ = tool_description  # ← captured parameter
    return mcp_tool_wrapper
func = make_tool_func(tool.name, tool.description)
```

### `core/config.py`

Added two new settings read from environment / `.env`:

| Setting | Env var | Default | Purpose |
|---------|---------|---------|---------|
| `mcp_enabled` | `MCP_ENABLED` | `True` | Master switch for MCP startup |
| `mcp_servers_config` | `MCP_SERVERS_CONFIG` | `config/mcp_servers.yaml` | Path to MCP server definitions |

### `main.py`

| Change | Purpose |
|--------|---------|
| `from tools.mcp_loader import MCPServerManager` | Import |
| `import skills.local.meta  # registers create_skill, fix_skill` | Updated comment |
| MCP connect block in `lifespan` startup (before heartbeat) | Connect servers, register tools |
| `try/except` around `mcp_manager.connect_all()` | Malformed YAML or unexpected error does not crash agent startup |
| `mcp_manager.close_all()` in `lifespan` shutdown | Graceful disconnect |

**MCP startup block:**
```python
if settings.mcp_enabled:
    logger.info("Connecting MCP servers (web search, fetch, browser)...")
    mcp_manager = MCPServerManager(
        config_path=settings.mcp_servers_config,
        event_bus=event_bus,
        registry=registry,
    )
    try:
        await mcp_manager.connect_all()
        app.state.mcp_manager = mcp_manager
    except Exception as e:
        logger.warning("MCP startup failed — continuing without MCP servers: %s", e)
```

### `requirements.txt`

`mcp>=0.1.0` → `mcp>=1.0.0`

The `ClientSession`, `StdioServerParameters`, and `stdio_client` APIs are stable from 1.0.0. The project was already using these APIs; the version floor just needed updating to reflect reality.

### `.env.example`

Added `BRAVE_API_KEY` documentation:
```
# MCP Servers
# Fetch and Playwright require no API key.
# Brave Search: free tier 2,000 queries/month — https://brave.com/search/api/
# BRAVE_API_KEY=
```

### `deploy/dolOS.service`

Added second `ExecStartPre` line to install Playwright's Chromium browser automatically on service start:
```
ExecStartPre=/bin/bash -c 'npx --yes playwright install chromium 2>/dev/null || true'
```
The `|| true` ensures the service is not blocked if Node.js is absent. `playwright install` is idempotent — it skips if Chromium is already installed.

---

## Peer Review Fixes Applied

A second review agent identified these issues before merge:

| Severity | File | Issue | Fix applied |
|----------|------|-------|-------------|
| CRITICAL | `tools/mcp_loader.py` | `from mcp import StdioServerParameters` was a top-level import — crashes agent on startup if `mcp` package is absent even with `MCP_ENABLED=false` | Moved to lazy import inside `connect_all()` with `ImportError` guard |
| WARNING | `skills/executor.py` | `asyncio.TimeoutError` branch did not append the self-correction hint | Added same hint as the `Exception` branch |
| WARNING | `tools/mcp_client.py` | `__doc__` closure over loop variable `tool` | Fixed by passing `tool_description` as explicit parameter |
| WARNING | `main.py` | `connect_all()` not wrapped in `try/except` — malformed YAML crashes lifespan | Added `try/except` with warning log |
| WARNING | `tests/tools/` | No tests for `MCPServerManager` | Created `tests/tools/test_mcp_loader.py` (11 tests) |
| INFO | `main.py` | Comment only mentioned `create_skill`, not `fix_skill` | Updated comment |

---

## Activation on Deployment Server

```bash
# 1. Install Node.js 18+
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# 2. Update Python packages
cd /opt/dolOS && pip install -r requirements.txt

# 3. (Optional) Enable Brave web search
echo "BRAVE_API_KEY=your_key_here" >> /opt/dolOS/.env
# Free tier: https://brave.com/search/api/

# 4. Restart service (Chromium installs automatically via ExecStartPre)
sudo systemctl restart dolOS

# 5. Verify MCP connected
journalctl -u dolOS -n 30 | grep -i mcp
```

---

## Rollback

```bash
git log --oneline   # find commit before these changes
git revert <hash>
```

To disable MCP without reverting code, add to `.env`:
```
MCP_ENABLED=false
```
The agent starts normally with no MCP tools registered.
