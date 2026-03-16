import os
import tempfile
from pathlib import Path
import pytest

from skills.local.filesystem import read_file, write_file, set_sandbox_dir

@pytest.fixture
def sandbox_env():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir).absolute()
        set_sandbox_dir(temp_path)
        yield temp_path

def test_write_and_read_file_within_sandbox(sandbox_env):
    test_file = sandbox_env / "test.txt"
    
    # Write
    result = write_file(str(test_file), "Hello Sandbox")
    assert "Successfully wrote to" in result
    assert test_file.exists()
    
    # Read
    content = read_file(str(test_file))
    assert content == "Hello Sandbox"

def test_read_file_not_found(sandbox_env):
    missing_file = sandbox_env / "missing.txt"
    with pytest.raises(FileNotFoundError):
        read_file(str(missing_file))

def test_access_outside_sandbox(sandbox_env):
    # Attempt to write to a parent directory
    outside_file = sandbox_env.parent / "sneaky.txt"
    
    with pytest.raises(PermissionError, match="outside the allowed sandbox"):
        write_file(str(outside_file), "sneaky")
        
    with pytest.raises(PermissionError, match="outside the allowed sandbox"):
        read_file(str(outside_file))
