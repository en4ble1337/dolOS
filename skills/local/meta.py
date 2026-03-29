"""Meta-skills that allow the agent to extend its own capabilities."""
import ast
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

    # --- Pre-write validation ---

    # 1. Syntax check: catches SyntaxError before anything touches disk
    try:
        tree = ast.parse(file_content)
    except SyntaxError as e:
        return f"Error: Syntax error in generated code — {e}"

    # 2. Structure check: the code must define an async function named 'handler'
    has_handler = any(
        isinstance(node, ast.AsyncFunctionDef) and node.name == "handler"
        for node in ast.walk(tree)
    )
    if not has_handler:
        return "Error: Generated code must contain an async function named 'handler'."

    # --- Write then import-validate ---

    skill_file.write_text(file_content, encoding="utf-8")

    # Dynamically import so it registers immediately without restarting
    module_name = f"skills.local.generated.{name}"
    try:
        if module_name in sys.modules:
            # Reload if already imported (e.g. re-creating same skill)
            module = importlib.reload(sys.modules[module_name])
        else:
            spec = importlib.util.spec_from_file_location(module_name, skill_file)
            if spec is None or spec.loader is None:
                skill_file.unlink(missing_ok=True)
                return f"Error: Could not load skill file at {skill_file}"
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as e:
        # Import failed (bad imports, runtime error at module level) — remove the broken file
        # so it doesn't get auto-loaded on the next restart
        skill_file.unlink(missing_ok=True)
        sys.modules.pop(module_name, None)
        return f"Error: Skill code failed to import — {e}"

    return f"Skill '{name}' created and registered. It will persist across restarts."


@skill(
    name="fix_skill",
    description=(
        "Retrieve the full source code of a previously generated skill so you can review and "
        "rewrite it. Use this when a generated skill fails at runtime: read its current code, "
        "identify the bug, then call create_skill with the same name and corrected code to "
        "overwrite it. Only works for agent-created skills in the generated/ directory."
    ),
)
async def fix_skill(name: str) -> str:
    """Return the source of a generated skill file for review and rewriting.

    Args:
        name: The snake_case name of the generated skill to retrieve.

    Returns:
        The full Python source of the skill file, or an error message if not found.
    """
    skill_file = _GENERATED_DIR / f"{name}.py"
    if not skill_file.exists():
        return (
            f"Error: No generated skill named '{name}' found. "
            "Only agent-created skills (in generated/) can be retrieved this way."
        )
    return skill_file.read_text(encoding="utf-8")
