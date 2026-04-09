"""Tests for MCPServerRunner (Gap 8).

TDD Red phase — these tests MUST FAIL before tools/mcp_server.py exists.

MCPServerRunner speaks the MCP JSON-RPC protocol over stdio.
We test _dispatch() directly (unit tests) — no real stdin/stdout needed.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runner(registry: SkillRegistry | None = None) -> "MCPServerRunner":
    from tools.mcp_server import MCPServerRunner
    reg = registry or SkillRegistry()
    return MCPServerRunner(reg)


def _make_request(method: str, req_id: int = 1, params: dict | None = None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params:
        msg["params"] = params
    return msg


# ---------------------------------------------------------------------------
# initialize handshake
# ---------------------------------------------------------------------------

class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_returns_ok(self):
        runner = _make_runner()
        msg = _make_request("initialize", req_id=1)
        response = await runner._dispatch(msg)
        assert response is not None
        assert response.get("id") == 1
        assert "result" in response
        assert response.get("error") is None

    @pytest.mark.asyncio
    async def test_initialize_contains_protocol_version(self):
        runner = _make_runner()
        msg = _make_request("initialize", req_id=2)
        response = await runner._dispatch(msg)
        result = response["result"]
        assert "protocolVersion" in result

    @pytest.mark.asyncio
    async def test_initialize_contains_server_info(self):
        runner = _make_runner()
        msg = _make_request("initialize", req_id=3)
        response = await runner._dispatch(msg)
        result = response["result"]
        assert "serverInfo" in result
        assert result["serverInfo"]["name"] == "dolOS"


class TestInitializedNotification:
    @pytest.mark.asyncio
    async def test_initialized_notification_returns_none(self):
        """notifications/initialized is a notification — no response expected."""
        runner = _make_runner()
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        response = await runner._dispatch(msg)
        assert response is None


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------

class TestToolsList:
    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_tools(self):
        runner = _make_runner()
        msg = _make_request("tools/list")
        response = await runner._dispatch(msg)
        assert response["result"]["tools"] == []

    @pytest.mark.asyncio
    async def test_registered_skill_appears_in_tools_list(self):
        reg = SkillRegistry()
        reg.register("read_file", "Read a file", lambda path: "content", is_read_only=True)

        runner = _make_runner(reg)
        msg = _make_request("tools/list")
        response = await runner._dispatch(msg)

        tools = response["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "read_file" in names

    @pytest.mark.asyncio
    async def test_tool_entry_has_required_mcp_fields(self):
        reg = SkillRegistry()
        reg.register("my_skill", "Does stuff", lambda: None)

        runner = _make_runner(reg)
        msg = _make_request("tools/list")
        response = await runner._dispatch(msg)

        tool = response["result"]["tools"][0]
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool

    @pytest.mark.asyncio
    async def test_multiple_skills_all_appear(self):
        reg = SkillRegistry()
        reg.register("skill_a", "A", lambda: None)
        reg.register("skill_b", "B", lambda: None)
        reg.register("skill_c", "C", lambda: None)

        runner = _make_runner(reg)
        msg = _make_request("tools/list")
        response = await runner._dispatch(msg)

        names = {t["name"] for t in response["result"]["tools"]}
        assert names == {"skill_a", "skill_b", "skill_c"}


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------

class TestToolsCall:
    @pytest.mark.asyncio
    async def test_call_known_sync_skill_returns_result(self):
        reg = SkillRegistry()
        reg.register("echo", "Echoes input", lambda text: f"echo:{text}")

        runner = _make_runner(reg)
        msg = _make_request("tools/call", params={"name": "echo", "arguments": {"text": "hello"}})
        response = await runner._dispatch(msg)

        content = response["result"]["content"]
        assert any("echo:hello" in item["text"] for item in content)

    @pytest.mark.asyncio
    async def test_call_known_async_skill_returns_result(self):
        reg = SkillRegistry()

        async def async_echo(text: str) -> str:
            return f"async:{text}"

        reg.register("async_echo", "Async echo", async_echo)
        runner = _make_runner(reg)
        msg = _make_request("tools/call", params={"name": "async_echo", "arguments": {"text": "world"}})
        response = await runner._dispatch(msg)

        content = response["result"]["content"]
        assert any("async:world" in item["text"] for item in content)

    @pytest.mark.asyncio
    async def test_call_unknown_skill_returns_error_content(self):
        runner = _make_runner()
        msg = _make_request("tools/call", params={"name": "nonexistent", "arguments": {}})
        response = await runner._dispatch(msg)

        # Should still be a valid response (not an RPC error), but content describes the failure
        content = response["result"]["content"]
        assert any("not found" in item["text"].lower() or "error" in item["text"].lower() for item in content)

    @pytest.mark.asyncio
    async def test_call_skill_that_raises_returns_error_content(self):
        reg = SkillRegistry()

        def boom(**kwargs):
            raise RuntimeError("skill exploded")

        reg.register("boom", "Explodes", boom)
        runner = _make_runner(reg)
        msg = _make_request("tools/call", params={"name": "boom", "arguments": {}})
        response = await runner._dispatch(msg)

        content = response["result"]["content"]
        assert any("error" in item["text"].lower() for item in content)


# ---------------------------------------------------------------------------
# Unknown methods
# ---------------------------------------------------------------------------

class TestUnknownMethod:
    @pytest.mark.asyncio
    async def test_unknown_method_returns_rpc_error(self):
        runner = _make_runner()
        msg = _make_request("completely/unknown", req_id=99)
        response = await runner._dispatch(msg)

        assert "error" in response
        assert response["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_rpc_error_preserves_request_id(self):
        runner = _make_runner()
        msg = _make_request("no/such/method", req_id=42)
        response = await runner._dispatch(msg)
        assert response["id"] == 42
