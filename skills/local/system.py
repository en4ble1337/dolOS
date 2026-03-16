import asyncio
from skills.registry import skill

@skill(
    name="run_command",
    description="Run a system command in the terminal. Useful for running build scripts, listing files outside sandbox, etc."
)
async def run_command(command: str, timeout_seconds: float = 30.0) -> str:
    """Executes a system shell command and returns the output (stdout + stderr).
    Output is truncated to avoid overwhelming the context.
    """
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        try:
            stdout_bytes, _ = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            return f"Timeout Error: Command exceeded {timeout_seconds} seconds."

        output = stdout_bytes.decode('utf-8', errors='replace').strip()
        
        # Truncate output to prevent massive context bloat
        max_length = 2000
        if len(output) > max_length:
            output = output[:max_length] + "\n...[Output truncated]..."

        if process.returncode != 0:
            if not output:
                return f"Exit Code: {process.returncode}"
            return f"{output}\nExit Code: {process.returncode}"
            
        return output if output else "Command executed successfully with no output."

    except Exception as e:
        return f"Execution Error: {str(e)}"
