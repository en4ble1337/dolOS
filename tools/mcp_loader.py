"""Load and connect all MCP servers defined in config/mcp_servers.yaml."""
import logging
import os
import re
from pathlib import Path

import yaml

from core.telemetry import EventBus
from skills.registry import SkillRegistry
from tools.mcp_client import MCPClientWrapper

logger = logging.getLogger(__name__)


def _expand_env(value: str) -> tuple[str, bool]:
    """Expand ${VAR} references against the process environment.

    Returns (resolved_value, all_vars_resolved). all_vars_resolved is False
    if any ${...} placeholder remained after expansion.
    """
    resolved = os.path.expandvars(str(value))
    still_unresolved = bool(re.search(r"\$\{[^}]+\}", resolved))
    return resolved, not still_unresolved


class MCPServerManager:
    """Manages the full lifecycle of all configured MCP server connections.

    On startup, loads `config/mcp_servers.yaml`, connects to each enabled server,
    and registers its tools into the shared SkillRegistry so the LLM can call them
    like any built-in skill.

    Servers marked `optional: true` are silently skipped when their env vars are
    missing or their command fails (e.g. Playwright not installed). Non-optional
    servers log a warning but do not crash the agent.
    """

    def __init__(
        self,
        config_path: str,
        event_bus: EventBus,
        registry: SkillRegistry,
    ) -> None:
        self.config_path = config_path
        self.event_bus = event_bus
        self.registry = registry
        self._clients: list[MCPClientWrapper] = []

    async def connect_all(self) -> int:
        """Load the YAML config and connect to every enabled MCP server.

        Returns:
            Number of servers successfully connected.
        """
        config_file = Path(self.config_path)
        if not config_file.exists():
            logger.warning(
                "MCP config not found at '%s' — no MCP servers will be loaded. "
                "Copy config/mcp_servers.yaml to enable web search and browser tools.",
                self.config_path,
            )
            return 0

        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        servers: dict = config.get("mcpServers", {})
        if not servers:
            logger.info("No mcpServers entries in %s.", self.config_path)
            return 0

        # Lazy import — keeps agent startable even if mcp package is missing
        try:
            from mcp import StdioServerParameters
        except ImportError:
            logger.warning(
                "mcp package not installed — MCP servers disabled. "
                "Run: pip install 'mcp>=1.0.0'"
            )
            return 0

        connected = 0
        for name, spec in servers.items():
            if not spec.get("enabled", True):
                logger.info("MCP server '%s' disabled — skipping.", name)
                continue

            command: str = spec.get("command", "npx")
            args: list[str] = [str(a) for a in spec.get("args", [])]
            optional: bool = spec.get("optional", False)
            env_spec: dict = spec.get("env") or {}

            # Resolve every env var referenced in the spec
            resolved_env: dict[str, str] = {}
            skip = False
            for key, raw_value in env_spec.items():
                resolved, ok = _expand_env(str(raw_value))
                if not ok:
                    if optional:
                        logger.info(
                            "MCP server '%s' skipped — env var '%s' not set in .env. "
                            "Add it to enable this server.",
                            name, key,
                        )
                        skip = True
                        break
                    else:
                        logger.warning(
                            "MCP server '%s': env var '%s' not set — attempting to start anyway.",
                            name, key,
                        )
                resolved_env[key] = resolved

            if skip:
                continue

            params = StdioServerParameters(
                command=command,
                args=args,
                env=resolved_env if resolved_env else None,
            )
            client = MCPClientWrapper(params, self.event_bus, self.registry)
            try:
                await client.connect()
                await client.bind_tools()
                self._clients.append(client)
                connected += 1
                logger.info("MCP server '%s' connected and tools registered.", name)
            except Exception as exc:
                if optional:
                    logger.info(
                        "MCP server '%s' could not start (%s) — skipped. "
                        "Check that Node.js is installed and the command is correct.",
                        name, exc,
                    )
                else:
                    logger.warning(
                        "MCP server '%s' failed to connect: %s", name, exc
                    )

        if connected:
            registered = self.registry.get_all_skill_names()
            logger.info(
                "MCP startup complete: %d server(s) connected. Total registered skills: %d.",
                connected, len(registered),
            )
        else:
            logger.info("MCP startup complete: no servers connected.")

        return connected

    async def close_all(self) -> None:
        """Gracefully disconnect all active MCP servers."""
        for client in self._clients:
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
        logger.info("All MCP servers disconnected.")
