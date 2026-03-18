"""Meta-skills that allow the agent to extend its own capabilities."""
import importlib
import importlib.util
import sys
from pathlib import Path

from skills.registry import skill

_GENERATED_DIR = Path(__file__).parent / "generated"


@skill(
    name="create_skill",
    description=(
        "Write a new persistent skill and register it immediately. Use this when no existing "
        "skill can solve a task — write Python code to handle it, save it, and it becomes "
        "available in this session and all future sessions. "
        "The `code` parameter must be a complete Python async function named exactly `handler` "
        "that accepts keyword arguments and returns a string result."
    ),
)
async def create_skill(name: str, description: str, code: str) -> str:
    """Persist a new skill as a Python file and register it in the current process.

    Args:
        name: Unique snake_case skill name (e.g. 'get_weather').
        description: One-sentence description shown to the LLM.
        code: Complete Python code for an async function named `handler`.
              Must use only stdlib or packages already installed.

    Returns:
        Confirmation message with the registered skill name.
    """
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    skill_file = _GENERATED_DIR / f"{name}.py"

    file_content = f'''"""Auto-generated skill: {name}"""
from skills.registry import skill


@skill(name={name!r}, description={description!r})
{code}
'''

    skill_file.write_text(file_content, encoding="utf-8")

    # Dynamically import so it registers immediately without restarting
    module_name = f"skills.local.generated.{name}"
    if module_name in sys.modules:
        # Reload if already imported (e.g. re-creating same skill)
        module = importlib.reload(sys.modules[module_name])
    else:
        spec = importlib.util.spec_from_file_location(module_name, skill_file)
        if spec is None or spec.loader is None:
            return f"Error: Could not load skill file at {skill_file}"
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]

    return f"Skill '{name}' created and registered. It will persist across restarts."
