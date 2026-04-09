"""MCP stdio server — exposes dolOS skills to external MCP clients (Gap 8).

dolOS can act as an MCP *server*, making its skill registry available to
any MCP-capable client (Claude Desktop, mcp-inspector, other agents).

This is the inverse of ``tools/mcp_client.py`` (which makes dolOS a *client*
that calls out to external MCP servers).

Usage
-----
    python main.py --mcp

The server reads JSON-RPC 2.0 messages from stdin and writes responses to
stdout, conforming to the MCP 2024-11-05 protocol subset:

    - initialize / notifications/initialized
    - tools/list
    - tools/call

Design notes
------------
* ``MCPServerRunner`` is pure application logic — no stdin/stdout wiring.
  ``run()`` handles the IO; ``_dispatch()`` handles the protocol and is
  unit-testable in isolation.
* Skill errors are returned as text content (not RPC errors) to follow the
  MCP spec: tool invocation failures are reported in the content payload.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_MCP_PROTOCOL_VERSION = "2024-11-05"
_SERVER_NAME = "dolOS"
_SERVER_VERSION = "0.1.0"


class MCPServerRunner:
    """Minimal MCP stdio server backed by a :class:`~skills.registry.SkillRegistry`.

    Implements the MCP JSON-RPC protocol subset needed for tool discovery
    (``tools/list``) and invocation (``tools/call``).

    Args:
        registry: The skill registry containing all registered skills to expose.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Read JSON-RPC lines from stdin and write responses to stdout.

        Runs until stdin is closed (EOF) or the process is terminated.
        Each line must be a complete JSON-RPC 2.0 message.
        """
        logger.info("[MCP_SERVER] dolOS MCP server starting on stdio")
        loop = asyncio.get_running_loop()

        reader = asyncio.StreamReader()
        read_protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: read_protocol, sys.stdin.buffer)

        write_transport, _ = await loop.connect_write_pipe(
            asyncio.BaseProtocol, sys.stdout.buffer
        )

        async for raw_bytes in reader:
            line = raw_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("[MCP_SERVER] Bad JSON: %s", line[:120])
                continue

            response = await self._dispatch(msg)
            if response is not None:
                out = json.dumps(response) + "\n"
                write_transport.write(out.encode("utf-8"))

    # ------------------------------------------------------------------
    # Protocol dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one JSON-RPC message and return the response (or None for notifications).

        Args:
            msg: Decoded JSON-RPC 2.0 message dict.

        Returns:
            A JSON-RPC response dict, or ``None`` for notification messages that
            require no response.
        """
        method: str = msg.get("method", "")
        req_id: Any = msg.get("id")

        if method == "initialize":
            return self._ok(req_id, {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": _SERVER_NAME,
                    "version": _SERVER_VERSION,
                },
            })

        if method == "notifications/initialized":
            # Notification — no response
            return None

        if method == "tools/list":
            tools = self._build_tools_list()
            return self._ok(req_id, {"tools": tools})

        if method == "tools/call":
            params: dict[str, Any] = msg.get("params") or {}
            name: str = params.get("name", "")
            arguments: dict[str, Any] = params.get("arguments") or {}
            result_text = await self._call_tool(name, arguments)
            return self._ok(req_id, {
                "content": [{"type": "text", "text": str(result_text)}],
            })

        # Unknown method — return JSON-RPC error
        return self._error(req_id, -32601, f"Method not found: {method}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_tools_list(self) -> list[dict[str, Any]]:
        """Build the MCP tools list from the skill registry."""
        tools: list[dict[str, Any]] = []
        for schema in self.registry.get_all_schemas():
            tools.append({
                "name": schema["name"],
                "description": schema.get("description", ""),
                "inputSchema": schema.get("parameters", {"type": "object", "properties": {}}),
            })
        return tools

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a skill by name with the given arguments.

        Returns the result as a string, or an error message string if the
        skill is not found or raises an exception.
        """
        try:
            skill_fn = self.registry.get_skill(name)
        except KeyError:
            return f"Error: skill '{name}' not found."
        try:
            result = skill_fn(**arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as exc:
            logger.exception("[MCP_SERVER] Tool '%s' raised: %s", name, exc)
            return f"Error executing '{name}': {exc}"

    # ------------------------------------------------------------------
    # JSON-RPC helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ok(req_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
