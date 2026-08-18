"""Tests for the skill execution sandbox."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.telemetry import EventBus, EventType
from skills.sandbox import SandboxExecutor, SandboxPolicy, validate_path_access


@pytest.fixture
def mock_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    bus.emit_sync = MagicMock()
    return bus


class TestSandboxPolicy:
    def test_defaults(self) -> None:
        policy = SandboxPolicy()
        assert policy.timeout == 30.0
        assert policy.max_output_length == 4000
        assert policy.allow_network is False
        assert policy.allowed_paths == []

    def test_custom_values(self) -> None:
        policy = SandboxPolicy(
            allowed_paths=["/tmp"],
            timeout=10.0,
            max_output_length=1000,
            allow_network=True,
        )
        assert policy.allowed_paths == ["/tmp"]
        assert policy.timeout == 10.0
        assert policy.allow_network is True


class TestValidatePathAccess:
    def test_no_restrictions_allows_all(self) -> None:
        assert validate_path_access("/any/path", []) is True

    def test_allowed_path(self, tmp_path) -> None:
        assert validate_path_access(str(tmp_path / "file.txt"), [str(tmp_path)]) is True

    def test_disallowed_path(self, tmp_path) -> None:
        assert validate_path_access("/etc/passwd", [str(tmp_path)]) is False

    def test_sibling_prefix_path_is_disallowed(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        sibling = tmp_path / "allowed_sneaky"
        allowed.mkdir()
        sibling.mkdir()

        assert validate_path_access(str(sibling / "secret.txt"), [str(allowed)]) is False


class TestSandboxExecutor:
    @pytest.mark.asyncio
    async def test_execute_simple_command(self) -> None:
        executor = SandboxExecutor()
        result = await executor.execute_command(f"{sys.executable} -c \"print('hello')\"")

        assert result["success"] is True
        assert "hello" in result["output"]
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_execute_command_timeout(self) -> None:
        executor = SandboxExecutor()
        policy = SandboxPolicy(timeout=0.5)

        result = await executor.execute_command(
            f'{sys.executable} -c "import time; time.sleep(10)"',
            policy=policy,
        )

        assert result["success"] is False
        assert "Timeout" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_command_failure(self) -> None:
        executor = SandboxExecutor()
        result = await executor.execute_command(f'{sys.executable} -c "raise SystemExit(1)"')

        assert result["success"] is False
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_execute_command_truncation(self) -> None:
        executor = SandboxExecutor()
        policy = SandboxPolicy(max_output_length=20)

        result = await executor.execute_command(
            f"{sys.executable} -c \"print('A' * 1000)\"",
            policy=policy,
        )

        assert result["truncated"] is True
        assert len(result["output"]) < 1000

    @pytest.mark.asyncio
    async def test_execute_code(self) -> None:
        executor = SandboxExecutor()
        result = await executor.execute_code("print(2 + 2)")

        assert result["success"] is True
        assert "4" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_code_error(self) -> None:
        executor = SandboxExecutor()
        result = await executor.execute_code("raise ValueError('boom')")

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_code_rejects_sibling_prefix_path(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        sibling = tmp_path / "allowed_sneaky"
        allowed.mkdir()
        sibling.mkdir()
        sneaky_file = sibling / "secret.txt"
        sneaky_file.write_text("outside", encoding="utf-8")

        executor = SandboxExecutor()
        policy = SandboxPolicy(allowed_paths=[str(allowed)])
        result = await executor.execute_code(
            f"print(open(r'{sneaky_file}', 'r', encoding='utf-8').read())",
            policy=policy,
        )

        assert result["success"] is False
        assert "Access denied" in result["output"]

    @pytest.mark.asyncio
    async def test_telemetry_emitted_on_command(self, mock_event_bus: EventBus) -> None:
        executor = SandboxExecutor(event_bus=mock_event_bus)
        await executor.execute_command(f"{sys.executable} -c \"print('hi')\"")

        emitted_types = [call.args[0].event_type for call in mock_event_bus.emit.await_args_list]
        assert EventType.TOOL_INVOKE in emitted_types
        assert EventType.TOOL_COMPLETE in emitted_types

    @pytest.mark.asyncio
    async def test_telemetry_emitted_on_error(self, mock_event_bus: EventBus) -> None:
        executor = SandboxExecutor(event_bus=mock_event_bus)
        policy = SandboxPolicy(timeout=0.5)

        await executor.execute_command(
            f'{sys.executable} -c "import time; time.sleep(10)"',
            policy=policy,
        )

        emitted_types = [call.args[0].event_type for call in mock_event_bus.emit.await_args_list]
        assert EventType.TOOL_INVOKE in emitted_types
        # Timeout results in a non-success TOOL_COMPLETE, not TOOL_ERROR
        assert EventType.TOOL_COMPLETE in emitted_types

    @pytest.mark.asyncio
    async def test_sandbox_env_includes_policy(self) -> None:
        executor = SandboxExecutor()
        policy = SandboxPolicy(allowed_paths=["/tmp"], allow_network=False)
        env = executor._build_sandbox_env(policy)

        assert "SANDBOX_ALLOWED_PATHS" in env
        assert "SANDBOX_ALLOW_NETWORK" in env
        assert env["SANDBOX_ALLOW_NETWORK"] == "0"
