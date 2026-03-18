"""Auto-loads all agent-generated skill files from this directory."""
import importlib
from pathlib import Path

_here = Path(__file__).parent

for _f in sorted(_here.glob("*.py")):
    if _f.name != "__init__.py":
        importlib.import_module(f"skills.local.generated.{_f.stem}")
