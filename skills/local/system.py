import os

from skills.registry import skill
from skills.sandbox import SandboxExecutor, SandboxPolicy

# Module-level sandbox executor (lazily initialised on first call)
_sandbox: SandboxExecutor | None = None


def _get_sandbox() -> SandboxExecutor:
    """Return the shared SandboxExecutor, creating it on first access."""
    global _sandbox
    if _sandbox is None:
        default_policy = SandboxPolicy(
            allowed_paths=[os.getcwd()],
            timeout=30.0,
            max_output_length=2000,
            allow_network=False,
        )
        _sandbox = SandboxExecutor(default_policy=default_policy)
    return _sandbox


@skill(
    name="run_command",
    description="Run a system command in the terminal. Useful for running build scripts, listing files outside sandbox, etc.",
)
async def run_command(command: str, timeout_seconds: float = 30.0) -> str:
    """Executes a system shell command inside a sandbox subprocess.

    The command runs with restricted filesystem access and network disabled
    by default. Output is truncated to avoid overwhelming the context.
    """
    sandbox = _get_sandbox()
    policy = SandboxPolicy(
        allowed_paths=sandbox.default_policy.allowed_paths,
        timeout=timeout_seconds,
        max_output_length=sandbox.default_policy.max_output_length,
        allow_network=sandbox.default_policy.allow_network,
    )

    result = await sandbox.execute_command(command, policy=policy)

    if result["success"]:
        return result["output"] if result["output"] else "Command executed successfully with no output."

    return result["output"]
