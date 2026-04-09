"""Session notes skills — read/write per-session markdown notes (Gap 15).

Each session has a single markdown file at:
    data/SESSION_NOTES/<session_id>.md   (default)

Override the directory via the SESSION_NOTES_DIR environment variable
(used in tests to isolate writes).

Skills registered
-----------------
- set_session_note(session_id, content)  — overwrite the session note
- get_session_note(session_id)           — read it back ("" if missing)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from skills.registry import skill

logger = logging.getLogger(__name__)

_DEFAULT_NOTES_DIR = "data/SESSION_NOTES"


def _notes_dir() -> Path:
    """Return the notes directory, honouring SESSION_NOTES_DIR env override."""
    d = Path(os.environ.get("SESSION_NOTES_DIR", _DEFAULT_NOTES_DIR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _note_path(session_id: str) -> Path:
    # Sanitise: replace any path separators so session IDs can't escape the dir
    safe_id = session_id.replace("/", "_").replace("\\", "_")
    return _notes_dir() / f"{safe_id}.md"


@skill(
    name="set_session_note",
    description=(
        "Write or overwrite the markdown session note for this session. "
        "Use this to record the current task, plan, or working context so it "
        "is automatically injected into future turns of this session. "
        "Pass the full desired content — the previous note is replaced."
    ),
    read_only=False,
    concurrency_safe=False,
)
async def set_session_note(session_id: str, content: str) -> str:
    """Persist *content* as the session note for *session_id*.

    Args:
        session_id: The current session identifier.
        content:    Markdown string to persist as the session note.

    Returns:
        Confirmation string with the file path.
    """
    path = _note_path(session_id)
    path.write_text(content, encoding="utf-8")
    logger.info("[SESSION_NOTE] Saved note for session=%s (%d chars)", session_id, len(content))
    return f"Session note saved ({len(content)} chars) → {path}"


@skill(
    name="get_session_note",
    description=(
        "Read the current session note for this session. "
        "Returns the full markdown content, or an empty string if no note exists."
    ),
    read_only=True,
    concurrency_safe=True,
)
async def get_session_note(session_id: str) -> str:
    """Return the session note for *session_id*, or "" if not found.

    Args:
        session_id: The current session identifier.

    Returns:
        Markdown content of the note, or "" if the file does not exist.
    """
    path = _note_path(session_id)
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    logger.debug("[SESSION_NOTE] Read note for session=%s (%d chars)", session_id, len(content))
    return content
