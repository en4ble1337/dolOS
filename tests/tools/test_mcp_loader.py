"""Tests for MCPServerManager (tools/mcp_loader.py)."""
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from tools.mcp_loader import MCPServerManager, _expand_env


# ---------------------------------------------------------------------------
# _expand_env
# ---------------------------------------------------------------------------

def test_expand_env_resolved(monkeypatch):
    monkeypatch.setenv("MY_KEY", "secret")
    resolved, ok = _expand_env("${MY_KEY}")
    assert resolved == "secret"
    assert ok is True


def test_expand_env_unresolved():
    # Ensure variable is NOT set
    os.environ.pop("DEFINITELY_NOT_SET_XYZ", None)
    resolved, ok = _expand_env("${DEFINITELY_NOT_SET_XYZ}")
    assert ok is False
    assert "${DEFINITELY_NOT_SET_XYZ}" in resolved


def test_expand_env_literal_value():
    resolved, ok = _expand_env("plain_string")
    assert resolved == "plain_string"
    assert ok is True


# ---------------------------------------------------------------------------
# MCPServerManager.connect_all — YAML loading
# ---------------------------------------------------------------------------

def _make_manager(tmp_path, yaml_content):
    config_file = tmp_path / "mcp_servers.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")
    event_bus = MagicMock()
    registry = MagicMock()
    return MCPServerManager(str(config_file), event_bus, registry)


@pytest.mark.asyncio
async def test_missing_config_returns_zero(tmp_path):
    manager = MCPServerManager(
        str(tmp_path / "nonexistent.yaml"),
        MagicMock(),
        MagicMock(),
    )
    count = await manager.connect_all()
    assert count == 0


@pytest.mark.asyncio
async def test_empty_yaml_returns_zero(tmp_path):
    manager = _make_manager(tmp_path, "")
    count = await manager.connect_all()
    assert count == 0


@pytest.mark.asyncio
async def test_no_mcp_servers_key_returns_zero(tmp_path):
    manager = _make_manager(tmp_path, "other_key: value\n")
    count = await manager.connect_all()
    assert count == 0


@pytest.mark.asyncio
async def test_disabled_server_skipped(tmp_path):
    yaml_content = yaml.dump({
        "mcpServers": {
            "fetch": {"command": "npx", "args": ["-y", "server-fetch"], "enabled": False}
        }
    })
    manager = _make_manager(tmp_path, yaml_content)
    count = await manager.connect_all()
    assert count == 0


@pytest.mark.asyncio
async def test_optional_server_skipped_when_env_missing(tmp_path, monkeypatch):
    os.environ.pop("BRAVE_API_KEY", None)
    yaml_content = yaml.dump({
        "mcpServers": {
            "brave-search": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"},
                "optional": True,
            }
        }
    })
    manager = _make_manager(tmp_path, yaml_content)
    count = await manager.connect_all()
    assert count == 0


@pytest.mark.asyncio
async def test_optional_server_connects_when_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "test_key_123")
    yaml_content = yaml.dump({
        "mcpServers": {
            "brave-search": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                "env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"},
                "optional": True,
            }
        }
    })
    manager = _make_manager(tmp_path, yaml_content)

    mock_client = AsyncMock()
    with patch("tools.mcp_loader.MCPClientWrapper", return_value=mock_client):
        count = await manager.connect_all()

    mock_client.connect.assert_awaited_once()
    mock_client.bind_tools.assert_awaited_once()
    assert count == 1


@pytest.mark.asyncio
async def test_optional_server_connect_failure_skipped(tmp_path):
    yaml_content = yaml.dump({
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": ["-y", "@playwright/mcp@latest", "--headless"],
                "optional": True,
            }
        }
    })
    manager = _make_manager(tmp_path, yaml_content)

    mock_client = AsyncMock()
    mock_client.connect.side_effect = FileNotFoundError("npx not found")
    with patch("tools.mcp_loader.MCPClientWrapper", return_value=mock_client):
        count = await manager.connect_all()

    assert count == 0


@pytest.mark.asyncio
async def test_non_optional_server_connect_failure_logs_warning(tmp_path, caplog):
    import logging
    yaml_content = yaml.dump({
        "mcpServers": {
            "fetch": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-fetch"],
            }
        }
    })
    manager = _make_manager(tmp_path, yaml_content)

    mock_client = AsyncMock()
    mock_client.connect.side_effect = RuntimeError("connection refused")
    with patch("tools.mcp_loader.MCPClientWrapper", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="tools.mcp_loader"):
            count = await manager.connect_all()

    assert count == 0
    assert "failed to connect" in caplog.text


@pytest.mark.asyncio
async def test_mcp_not_installed_returns_zero(tmp_path):
    yaml_content = yaml.dump({
        "mcpServers": {"fetch": {"command": "npx", "args": []}}
    })
    manager = _make_manager(tmp_path, yaml_content)

    with patch.dict("sys.modules", {"mcp": None}):
        count = await manager.connect_all()

    assert count == 0


@pytest.mark.asyncio
async def test_close_all_calls_close_on_each_client(tmp_path):
    manager = MCPServerManager("irrelevant", MagicMock(), MagicMock())
    client_a = AsyncMock()
    client_b = AsyncMock()
    manager._clients = [client_a, client_b]

    await manager.close_all()

    client_a.close.assert_awaited_once()
    client_b.close.assert_awaited_once()
    assert manager._clients == []
