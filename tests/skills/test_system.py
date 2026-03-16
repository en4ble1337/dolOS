import pytest
import sys
import asyncio
from skills.local.system import run_command

@pytest.mark.asyncio
async def test_run_command_success():
    # Use python -c to print something cross-platform
    result = await run_command(f"{sys.executable} -c \"print('hello world')\"")
    assert "hello world" in result
    assert "Exit Code" not in result # Since exit code 0 usually omitted or explicitly state it in output

@pytest.mark.asyncio
async def test_run_command_failure():
    result = await run_command(f"{sys.executable} -c \"import sys; sys.exit(1)\"")
    assert "Exit Code: 1" in result

@pytest.mark.asyncio
async def test_run_command_timeout():
    # Sleep for 2 seconds, but we set a lower timeout for this test
    # Wait, the timeout is baked into run_command or the skill executor? 
    # Let's add a timeout param to run_command for safety since it's subprocess
    result = await run_command(f"{sys.executable} -c \"import time; time.sleep(2)\"", timeout_seconds=0.5)
    assert "Timeout" in result
