import os
from pathlib import Path

from skills.registry import skill

# By default, use current working dir, but allow override
SANDBOX_DIR = Path(os.getcwd()).absolute()

def set_sandbox_dir(path: str | Path) -> None:
    """Set the directory where file system operations are allowed."""
    global SANDBOX_DIR
    SANDBOX_DIR = Path(path).absolute()

def _ensure_safe_path(file_path: str) -> Path:
    """Ensure the path is within the sandbox directory."""
    target_path = Path(file_path).absolute()
    if not target_path.is_relative_to(SANDBOX_DIR):
        raise PermissionError(
            f"Access denied: Path {file_path} is outside the allowed sandbox directory."
        )
    return target_path

@skill(name="read_file", description="Read the contents of a file within the sandbox.", read_only=True, concurrency_safe=True)
def read_file(file_path: str) -> str:
    """Read the contents of a file from the file system."""
    safe_path = _ensure_safe_path(file_path)
    if not safe_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not safe_path.is_file():
        raise IsADirectoryError(f"Path is a directory, not a file: {file_path}")
    return safe_path.read_text(encoding="utf-8")

@skill(
    name="write_file",
    description="Write content to a file within the sandbox. Overwrites existing files.",
    read_only=False,
    concurrency_safe=False,
)
def write_file(file_path: str, content: str) -> str:
    """Write string content to a file on the file system."""
    safe_path = _ensure_safe_path(file_path)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_text(content, encoding="utf-8")
    return f"Successfully wrote to {file_path}"
