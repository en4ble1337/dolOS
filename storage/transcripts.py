"""TranscriptStore — append-only JSONL conversation transcripts.

Writes one JSON object per line to:
    data/transcripts/<session_id>.jsonl

Entry types
-----------
- "user"         : user message received
- "assistant"    : final assistant reply
- "tool_call"    : tool invoked by the LLM (name + arguments)
- "tool_result"  : result returned from tool execution (name + content)

Every entry always has:
- ``ts``         : ISO 8601 UTC timestamp
- ``type``       : one of the four types above
- ``session_id`` : the session this entry belongs to
- ...payload kwargs (e.g. ``content``, ``name``, ``arguments``)

Usage
-----
    store = TranscriptStore()                         # uses data/transcripts/
    store.append("sess-1", "user", content="Hello")
    store.append("sess-1", "assistant", content="Hi!")
    entries = store.read_session("sess-1")
    sessions = store.list_sessions()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = "data/transcripts"


class TranscriptStore:
    """Append-only JSONL store for session transcripts.

    Thread-safety: JSONL append is atomic at the OS level for lines < PIPE_BUF
    (typically 4 KiB), which covers almost all realistic entries.  For
    cross-process safety the caller should use a single ``TranscriptStore``
    instance per process.
    """

    def __init__(self, data_dir: str = _DEFAULT_DATA_DIR) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, session_id: str, entry_type: str, **payload: object) -> None:
        """Append a single entry to the session transcript.

        Args:
            session_id: The session this entry belongs to.
            entry_type: One of "user", "assistant", "tool_call", "tool_result".
            **payload: Arbitrary key-value data for the entry (e.g. content=, name=).
        """
        entry = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "type": entry_type,
            "session_id": session_id,
            **payload,
        }
        path = self._dir / f"{session_id}.jsonl"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("TranscriptStore: failed to write %s: %s", path, exc)

    def list_sessions(self) -> list[dict]:
        """Return metadata for all sessions that have transcripts.

        Each dict contains:
        - ``session_id``: the session identifier
        - ``entry_count``: number of entries in the transcript
        - ``path``: absolute path to the JSONL file (as string)
        """
        sessions: list[dict] = []
        for jsonl_file in sorted(self._dir.glob("*.jsonl")):
            session_id = jsonl_file.stem
            try:
                lines = [ln for ln in jsonl_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
                sessions.append({
                    "session_id": session_id,
                    "entry_count": len(lines),
                    "path": str(jsonl_file),
                })
            except OSError as exc:
                logger.warning("TranscriptStore: could not read %s: %s", jsonl_file, exc)
        return sessions

    def read_session(self, session_id: str) -> list[dict]:
        """Load all transcript entries for a session, in order.

        Args:
            session_id: The session to load.

        Returns:
            List of parsed entry dicts, or an empty list if the session has
            no transcript file.
        """
        path = self._dir / f"{session_id}.jsonl"
        if not path.exists():
            return []
        entries: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entries.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    logger.warning("TranscriptStore: skipping malformed line in %s: %s", path, exc)
        except OSError as exc:
            logger.warning("TranscriptStore: could not read %s: %s", path, exc)
        return entries
