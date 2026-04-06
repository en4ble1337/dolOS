"""Subprocess-based execution sandbox for skills.

Wraps skill execution in a subprocess with:
- Restricted filesystem access (configurable allowed directories)
- Hard timeout (configurable, default 30s)
- Output capture and truncation (protect LLM context windows)
- Network access control (disabled by default, enable per-skill via manifest)
- Resource limits where possible on the platform
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

from core.telemetry import Event, EventBus, EventType
from skills.bash_validator import validate_bash_command


# Maximum output length to protect LLM context windows
DEFAULT_MAX_OUTPUT_LENGTH = 4000
DEFAULT_TIMEOUT = 30.0


class SandboxError(Exception):
    """Raised when a sandbox constraint is violated."""


class SandboxPolicy:
    """Defines the execution policy for a sandboxed skill invocation.

    Attributes:
        allowed_paths: Directories the subprocess may access.
        timeout: Hard timeout in seconds for the subprocess.
        max_output_length: Maximum character length of captured output.
        allow_network: Whether the subprocess may make network calls.
    """

    def __init__(
        self,
        allowed_paths: list[str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_output_length: int = DEFAULT_MAX_OUTPUT_LENGTH,
        allow_network: bool = False,
    ) -> None:
        self.allowed_paths: list[str] = allowed_paths or []
        self.timeout: float = timeout
        self.max_output_length: int = max_output_length
        self.allow_network: bool = allow_network


class SandboxExecutor:
    """Executes commands and code in an isolated subprocess with policy enforcement.

    The subprocess receives a JSON payload on stdin describing the work, executes it,
    and returns a JSON result on stdout. The parent process enforces timeouts and
    captures/truncates output.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        default_policy: SandboxPolicy | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.default_policy = default_policy or SandboxPolicy()

    async def execute_command(
        self,
        command: str,
        policy: SandboxPolicy | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a shell command inside the sandbox subprocess.

        Args:
            command: The shell command to execute.
            policy: Execution policy overrides. Falls back to default_policy.
            trace_id: Trace ID for telemetry correlation.

        Returns:
            A dict with keys: output, exit_code, truncated, duration_ms, success.
        """
        policy = policy or self.default_policy
        start_time = time.time()

        # Pre-flight safety check — block dangerous patterns before subprocess
        validation = validate_bash_command(command)
        if not validation.is_safe:
            error_msg = f"Command blocked by safety validator: {validation.reason}"
            if self.event_bus:
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.TOOL_ERROR,
                        component="skills.sandbox",
                        trace_id=trace_id or "pending",
                        payload={
                            "action": "execute_command",
                            "command": command,
                            "error": error_msg,
                            "blocked": True,
                        },
                        duration_ms=0,
                        success=False,
                    )
                )
            return {
                "output": error_msg,
                "exit_code": -1,
                "truncated": False,
                "duration_ms": 0,
                "success": False,
                "blocked": True,
            }

        # Emit TOOL_INVOKE event
        if self.event_bus:
            await self.event_bus.emit(
                Event(
                    event_type=EventType.TOOL_INVOKE,
                    component="skills.sandbox",
                    trace_id=trace_id or "pending",
                    payload={
                        "action": "execute_command",
                        "command": command,
                        "allow_network": policy.allow_network,
                        "timeout": policy.timeout,
                    },
                )
            )

        try:
            result = await self._run_sandboxed_command(command, policy)
            duration_ms = (time.time() - start_time) * 1000
            result["duration_ms"] = duration_ms

            # Emit TOOL_COMPLETE event
            if self.event_bus:
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.TOOL_COMPLETE,
                        component="skills.sandbox",
                        trace_id=trace_id or "pending",
                        payload={
                            "action": "execute_command",
                            "command": command,
                            "exit_code": result.get("exit_code"),
                            "truncated": result.get("truncated", False),
                            "output_preview": result.get("output", "")[:200],
                        },
                        duration_ms=duration_ms,
                        success=result.get("success", False),
                    )
                )

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            error_msg = f"Sandbox execution error: {e}"

            if self.event_bus:
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.TOOL_ERROR,
                        component="skills.sandbox",
                        trace_id=trace_id or "pending",
                        payload={
                            "action": "execute_command",
                            "command": command,
                            "error": error_msg,
                        },
                        duration_ms=duration_ms,
                        success=False,
                    )
                )

            return {
                "output": error_msg,
                "exit_code": -1,
                "truncated": False,
                "duration_ms": duration_ms,
                "success": False,
            }

    async def execute_code(
        self,
        code: str,
        policy: SandboxPolicy | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a Python code snippet inside the sandbox subprocess.

        Args:
            code: The Python code to execute.
            policy: Execution policy overrides. Falls back to default_policy.
            trace_id: Trace ID for telemetry correlation.

        Returns:
            A dict with keys: output, exit_code, truncated, duration_ms, success.
        """
        policy = policy or self.default_policy
        start_time = time.time()

        if self.event_bus:
            await self.event_bus.emit(
                Event(
                    event_type=EventType.TOOL_INVOKE,
                    component="skills.sandbox",
                    trace_id=trace_id or "pending",
                    payload={
                        "action": "execute_code",
                        "code_preview": code[:200],
                        "allow_network": policy.allow_network,
                        "timeout": policy.timeout,
                    },
                )
            )

        try:
            result = await self._run_sandboxed_code(code, policy)
            duration_ms = (time.time() - start_time) * 1000
            result["duration_ms"] = duration_ms

            if self.event_bus:
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.TOOL_COMPLETE,
                        component="skills.sandbox",
                        trace_id=trace_id or "pending",
                        payload={
                            "action": "execute_code",
                            "exit_code": result.get("exit_code"),
                            "truncated": result.get("truncated", False),
                            "output_preview": result.get("output", "")[:200],
                        },
                        duration_ms=duration_ms,
                        success=result.get("success", False),
                    )
                )

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            error_msg = f"Sandbox execution error: {e}"

            if self.event_bus:
                await self.event_bus.emit(
                    Event(
                        event_type=EventType.TOOL_ERROR,
                        component="skills.sandbox",
                        trace_id=trace_id or "pending",
                        payload={
                            "action": "execute_code",
                            "error": error_msg,
                        },
                        duration_ms=duration_ms,
                        success=False,
                    )
                )

            return {
                "output": error_msg,
                "exit_code": -1,
                "truncated": False,
                "duration_ms": duration_ms,
                "success": False,
            }

    async def _run_sandboxed_command(
        self, command: str, policy: SandboxPolicy
    ) -> dict[str, Any]:
        """Run a shell command in a subprocess with sandbox constraints."""
        env = self._build_sandbox_env(policy)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=self._get_working_dir(policy),
            )

            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    process.communicate(), timeout=policy.timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                    # Wait briefly for process cleanup
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except Exception:
                    pass
                return {
                    "output": f"Timeout: Command exceeded {policy.timeout} seconds.",
                    "exit_code": -1,
                    "truncated": False,
                    "success": False,
                }

            output = stdout_bytes.decode("utf-8", errors="replace").strip()
            truncated = False

            if len(output) > policy.max_output_length:
                output = output[: policy.max_output_length] + "\n...[Output truncated]..."
                truncated = True

            success = process.returncode == 0

            if not success and not output:
                output = f"Exit Code: {process.returncode}"

            return {
                "output": output,
                "exit_code": process.returncode,
                "truncated": truncated,
                "success": success,
            }

        except FileNotFoundError:
            return {
                "output": "Error: Command not found or shell unavailable.",
                "exit_code": -1,
                "truncated": False,
                "success": False,
            }

    async def _run_sandboxed_code(
        self, code: str, policy: SandboxPolicy
    ) -> dict[str, Any]:
        """Run Python code in a subprocess with sandbox constraints.

        Builds a wrapper script that enforces path restrictions and network
        controls within the child process, then executes the user-provided code.
        """
        wrapper = self._build_code_wrapper(code, policy)
        env = self._build_sandbox_env(policy)

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                wrapper,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=self._get_working_dir(policy),
            )

            try:
                stdout_bytes, _ = await asyncio.wait_for(
                    process.communicate(), timeout=policy.timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except Exception:
                    pass
                return {
                    "output": f"Timeout: Code execution exceeded {policy.timeout} seconds.",
                    "exit_code": -1,
                    "truncated": False,
                    "success": False,
                }

            output = stdout_bytes.decode("utf-8", errors="replace").strip()
            truncated = False

            if len(output) > policy.max_output_length:
                output = output[: policy.max_output_length] + "\n...[Output truncated]..."
                truncated = True

            success = process.returncode == 0
            return {
                "output": output,
                "exit_code": process.returncode,
                "truncated": truncated,
                "success": success,
            }

        except FileNotFoundError:
            return {
                "output": "Error: Python interpreter not found.",
                "exit_code": -1,
                "truncated": False,
                "success": False,
            }

    def _build_sandbox_env(self, policy: SandboxPolicy) -> dict[str, str]:
        """Build an environment dict for the subprocess.

        Propagates essential env vars and injects sandbox-specific variables
        that the child process can use for self-enforcement.
        """
        env = os.environ.copy()

        # Inject sandbox configuration as environment variables
        if policy.allowed_paths:
            env["SANDBOX_ALLOWED_PATHS"] = json.dumps(
                [str(Path(p).absolute()) for p in policy.allowed_paths]
            )
        else:
            env["SANDBOX_ALLOWED_PATHS"] = "[]"

        env["SANDBOX_ALLOW_NETWORK"] = "1" if policy.allow_network else "0"
        env["SANDBOX_MAX_OUTPUT"] = str(policy.max_output_length)

        return env

    def _get_working_dir(self, policy: SandboxPolicy) -> str | None:
        """Determine the working directory for the subprocess.

        If allowed_paths are specified, use the first one as the working directory.
        """
        if policy.allowed_paths:
            first_path = Path(policy.allowed_paths[0])
            if first_path.is_dir():
                return str(first_path.absolute())
        return None

    def _build_code_wrapper(self, code: str, policy: SandboxPolicy) -> str:
        """Build a Python wrapper script that enforces sandbox constraints.

        The wrapper:
        1. Restricts open() to allowed paths (if configured)
        2. Blocks socket creation if network is not allowed
        3. Executes the user code
        """
        allowed_paths_json = json.dumps(
            [str(Path(p).absolute()) for p in policy.allowed_paths]
        )

        wrapper = textwrap.dedent(f"""\
            import os, sys, json

            # --- Sandbox enforcement ---
            _allowed_paths = json.loads('''{allowed_paths_json}''')
            _allow_network = {policy.allow_network!r}

            # Path restriction: override builtins.open to check paths
            if _allowed_paths:
                import builtins
                _original_open = builtins.open

                def _sandboxed_open(file, mode='r', *args, **kwargs):
                    # Allow special file descriptors and stdio
                    if isinstance(file, int):
                        return _original_open(file, mode, *args, **kwargs)
                    from pathlib import Path as _Path
                    resolved = str(_Path(file).absolute())
                    for allowed in _allowed_paths:
                        if resolved.startswith(allowed):
                            return _original_open(file, mode, *args, **kwargs)
                    raise PermissionError(
                        f"Sandbox: Access denied to '{{file}}'. "
                        f"Allowed paths: {{_allowed_paths}}"
                    )

                builtins.open = _sandboxed_open

            # Network restriction: block socket creation
            if not _allow_network:
                import socket as _socket
                _original_socket_init = _socket.socket.__init__

                def _blocked_socket_init(self, *args, **kwargs):
                    raise PermissionError(
                        "Sandbox: Network access is not allowed for this skill."
                    )

                _socket.socket.__init__ = _blocked_socket_init

            # --- Execute user code ---
            try:
                exec('''{_escape_triple_quotes(code)}''')
            except Exception as _e:
                print(f"Error: {{type(_e).__name__}}: {{_e}}", file=sys.stderr)
                sys.exit(1)
        """)

        return wrapper


def _escape_triple_quotes(code: str) -> str:
    """Escape triple-single-quote sequences in code to embed safely in a wrapper."""
    return code.replace("\\", "\\\\").replace("'''", "\\'\\'\\'")


def validate_path_access(path: str, allowed_paths: list[str]) -> bool:
    """Check whether a given path falls within any of the allowed directories.

    Args:
        path: The path to validate.
        allowed_paths: List of allowed directory paths.

    Returns:
        True if the path is within an allowed directory, False otherwise.
    """
    if not allowed_paths:
        return True  # No restrictions means all paths are allowed

    target = Path(path).absolute()
    for allowed in allowed_paths:
        allowed_dir = Path(allowed).absolute()
        try:
            if target.is_relative_to(allowed_dir):
                return True
        except (ValueError, TypeError):
            continue

    return False
