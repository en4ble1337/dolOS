"""Per-session key-value store for fast, exact recall.

Complements the vector memory (episodic/semantic) with a lightweight K/V
layer for structured session-scoped facts that benefit from exact lookup:
- user preferences ("preferred_language: Python")
- active task context ("current_branch: feature/xyz")
- temporary working assumptions

Each session's store is persisted as a JSON file under data/session_kv/.
An in-process cache avoids repeated file reads within a session.

The store is intentionally not wired into the system prompt yet — that
happens in Phase 2 (PromptBuilder). Only the K/V skills are registered
here so the LLM can write/read its own session state.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = "data/session_kv"


class SessionKVStore:
    """Per-session key-value store backed by JSON files on disk."""

    def __init__(self, data_dir: str = _DEFAULT_DATA_DIR) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        # In-process cache: {session_id: {key: value}}
        self._cache: dict[str, dict[str, str]] = {}

    def set(self, session_id: str, key: str, value: str) -> None:
        """Store a key-value pair for the given session."""
        store = self._load(session_id)
        store[key] = value
        self._save(session_id, store)

    def get(self, session_id: str, key: str) -> str | None:
        """Retrieve a value by key for the given session. Returns None if missing."""
        return self._load(session_id).get(key)

    def delete(self, session_id: str, key: str) -> bool:
        """Remove a key from the session store. Returns True if the key existed."""
        store = self._load(session_id)
        if key not in store:
            return False
        del store[key]
        self._save(session_id, store)
        return True

    def get_all(self, session_id: str) -> dict[str, str]:
        """Return a copy of the entire K/V store for a session."""
        return dict(self._load(session_id))

    def clear(self, session_id: str) -> None:
        """Remove all entries for a session."""
        self._save(session_id, {})

    def format_for_prompt(self, session_id: str) -> str:
        """Render the K/V store as a compact XML block for prompt injection.

        Returns an empty string if the store is empty so callers can safely
        concatenate without adding blank sections to the prompt.
        """
        store = self._load(session_id)
        if not store:
            return ""
        lines = "\n".join(f"  {k}: {v}" for k, v in sorted(store.items()))
        return f"<session_memory>\n{lines}\n</session_memory>\n\n"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self, session_id: str) -> dict[str, str]:
        if session_id not in self._cache:
            path = self._dir / f"{session_id}.json"
            if path.exists():
                try:
                    self._cache[session_id] = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("SessionKVStore: failed to load %s: %s", path, e)
                    self._cache[session_id] = {}
            else:
                self._cache[session_id] = {}
        return self._cache[session_id]

    def _save(self, session_id: str, store: dict[str, str]) -> None:
        path = self._dir / f"{session_id}.json"
        try:
            path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("SessionKVStore: failed to save %s: %s", path, e)
        self._cache[session_id] = store


# Module-level default instance (shared by the skill functions below)
_default_store = SessionKVStore()


def get_default_store() -> SessionKVStore:
    """Return the module-level default SessionKVStore instance."""
    return _default_store
