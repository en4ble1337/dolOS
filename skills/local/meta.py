"""Meta-skills that allow the agent to extend its own capabilities."""
import ast
import asyncio
import importlib
import importlib.util
import logging
import sys
from pathlib import Path

from skills.registry import skill

logger = logging.getLogger(__name__)

_GENERATED_DIR = Path(__file__).parent / "generated"
_STAGING_DIR = _GENERATED_DIR / "staging"


@skill(
    name="create_skill",
    description=(
        "Write a new persistent skill and register it immediately. Use this when no existing "
        "skill can solve a task — write Python code to handle it, save it, and it becomes "
        "available in this session and all future sessions. "
        "The `code` parameter must be a complete Python async function named exactly `handler` "
        "that accepts keyword arguments and returns a string result."
    ),
    read_only=False,
    concurrency_safe=False,
)
async def create_skill(
    name: str,
    description: str,
    code: str,
    is_read_only: bool = False,
    concurrency_safe: bool = False,
    quarantine: bool = True,
) -> str:
    """Persist a new skill as a Python file and register it in the current process.

    Args:
        name: Unique snake_case skill name (e.g. 'get_weather').
        description: One-sentence description shown to the LLM.
        code: Complete Python code for an async function named `handler`.
              Must use only stdlib or packages already installed.
        is_read_only: True if the skill never mutates external state. Defaults to False
              (conservative — generated skills should not be assumed safe to parallelise).
        concurrency_safe: True if the skill is safe to run concurrently with itself.
              Defaults to False for the same reason.
        quarantine: When True (default), the skill is written to a staging directory,
              smoke-tested by calling handler() with empty kwargs, then promoted to the
              live directory only on success. Pass quarantine=False for trusted,
              human-authored skills to skip the gate.

    Returns:
        Confirmation message with the registered skill name, or an error description.
    """
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    # Build the full live file content (used for both validation and final write)
    live_content = (
        f'"""Auto-generated skill: {name}"""\n'
        f"from skills.registry import skill\n"
        f"\n"
        f"\n"
        f"@skill("
        f"name={name!r}, description={description!r}, "
        f"read_only={is_read_only!r}, concurrency_safe={concurrency_safe!r})\n"
        f"{code}\n"
    )

    # --- Pre-write validation ---

    # 1. Syntax check: catches SyntaxError before anything touches disk
    try:
        tree = ast.parse(live_content)
    except SyntaxError as e:
        return f"Error: Syntax error in generated code — {e}"

    # 2. Structure check: the code must define an async function named 'handler'
    has_handler = any(
        isinstance(node, ast.AsyncFunctionDef) and node.name == "handler"
        for node in ast.walk(tree)
    )
    if not has_handler:
        return "Error: Generated code must contain an async function named 'handler'."

    # --- Quarantine / staging gate ---

    if quarantine:
        _STAGING_DIR.mkdir(parents=True, exist_ok=True)
        staging_file = _STAGING_DIR / f"{name}.py"

        # Write a staging file that contains ONLY the handler code (no @skill decorator)
        # so the import does not register the skill into the live registry.
        staging_content = (
            f'"""Staging validation for skill: {name} — do not import outside quarantine."""\n'
            f"{code}\n"
        )
        staging_file.write_text(staging_content, encoding="utf-8")

        staging_module_name = f"_dolOS_staging_{name}"
        try:
            staging_spec = importlib.util.spec_from_file_location(
                staging_module_name, staging_file
            )
            if staging_spec is None or staging_spec.loader is None:
                return f"Error: Could not load staging file at {staging_file}"

            staging_module = importlib.util.module_from_spec(staging_spec)
            sys.modules[staging_module_name] = staging_module
            staging_spec.loader.exec_module(staging_module)  # type: ignore[union-attr]

            # Smoke test: call handler() with no args.
            # TypeError means the function requires arguments but is otherwise callable — OK.
            # Any other exception means the skill has a real runtime defect.
            handler_fn = getattr(staging_module, "handler", None)
            if handler_fn is None:
                raise AttributeError("No 'handler' function found in staging module")

            try:
                coro = handler_fn()
                await asyncio.wait_for(coro, timeout=2.0)
            except TypeError:
                pass  # Expected when handler has required positional args
            # asyncio.TimeoutError / TimeoutError and other exceptions propagate to outer except

        except Exception as exc:
            sys.modules.pop(staging_module_name, None)
            err_type = type(exc).__name__
            logger.error(
                "Skill quarantine failed for '%s' (%s): %s", name, err_type, exc
            )
            return (
                f"Error: Skill quarantine failed ({err_type}) — {exc}\n"
                f"Skill source remains in staging at {staging_file} for diagnosis."
            )
        else:
            # Promotion succeeded — clean up staging file
            staging_file.unlink(missing_ok=True)
        finally:
            sys.modules.pop(staging_module_name, None)

    # --- Write live file then import-validate ---

    skill_file = _GENERATED_DIR / f"{name}.py"
    skill_file.write_text(live_content, encoding="utf-8")

    module_name = f"skills.local.generated.{name}"
    try:
        if module_name in sys.modules:
            # Reload if already imported (e.g. re-creating the same skill)
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
        # Import failed — remove the broken file so it is not auto-loaded on restart
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
    read_only=True,
    concurrency_safe=True,
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
