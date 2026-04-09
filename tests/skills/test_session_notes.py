"""Tests for session_notes skill (Gap 15).

TDD Red phase — these tests MUST FAIL before skills/local/session_notes.py exists.

set_session_note writes markdown to data/SESSION_NOTES/<session_id>.md.
get_session_note reads it back.  Missing file returns "".
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# set_session_note
# ---------------------------------------------------------------------------

class TestSetSessionNote:
    def test_creates_file_under_session_notes_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_NOTES_DIR", str(tmp_path / "SESSION_NOTES"))
        import importlib
        import skills.local.session_notes as mod
        importlib.reload(mod)

        _run(mod.set_session_note(session_id="sess-1", content="# Task\nDo something"))
        note_file = tmp_path / "SESSION_NOTES" / "sess-1.md"
        assert note_file.exists()

    def test_file_content_matches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_NOTES_DIR", str(tmp_path / "SESSION_NOTES"))
        import importlib
        import skills.local.session_notes as mod
        importlib.reload(mod)

        _run(mod.set_session_note(session_id="sess-2", content="# Notes\nHello world"))
        note_file = tmp_path / "SESSION_NOTES" / "sess-2.md"
        assert note_file.read_text(encoding="utf-8") == "# Notes\nHello world"

    def test_overwrites_existing_note(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_NOTES_DIR", str(tmp_path / "SESSION_NOTES"))
        import importlib
        import skills.local.session_notes as mod
        importlib.reload(mod)

        _run(mod.set_session_note(session_id="sess-3", content="first"))
        _run(mod.set_session_note(session_id="sess-3", content="second"))
        note_file = tmp_path / "SESSION_NOTES" / "sess-3.md"
        assert note_file.read_text(encoding="utf-8") == "second"

    def test_returns_confirmation_string(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_NOTES_DIR", str(tmp_path / "SESSION_NOTES"))
        import importlib
        import skills.local.session_notes as mod
        importlib.reload(mod)

        result = _run(mod.set_session_note(session_id="sess-4", content="note"))
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# get_session_note
# ---------------------------------------------------------------------------

class TestGetSessionNote:
    def test_returns_written_content(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_NOTES_DIR", str(tmp_path / "SESSION_NOTES"))
        import importlib
        import skills.local.session_notes as mod
        importlib.reload(mod)

        _run(mod.set_session_note(session_id="sess-5", content="# My note"))
        result = _run(mod.get_session_note(session_id="sess-5"))
        assert result == "# My note"

    def test_returns_empty_string_when_no_note(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_NOTES_DIR", str(tmp_path / "SESSION_NOTES"))
        import importlib
        import skills.local.session_notes as mod
        importlib.reload(mod)

        result = _run(mod.get_session_note(session_id="nonexistent-session"))
        assert result == ""

    def test_different_sessions_independent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_NOTES_DIR", str(tmp_path / "SESSION_NOTES"))
        import importlib
        import skills.local.session_notes as mod
        importlib.reload(mod)

        _run(mod.set_session_note(session_id="sess-a", content="note for A"))
        _run(mod.set_session_note(session_id="sess-b", content="note for B"))

        assert _run(mod.get_session_note(session_id="sess-a")) == "note for A"
        assert _run(mod.get_session_note(session_id="sess-b")) == "note for B"


# ---------------------------------------------------------------------------
# Skill registration
# ---------------------------------------------------------------------------

class TestSessionNotesSkillRegistration:
    def test_set_session_note_registered(self):
        import skills.local.session_notes  # noqa: F401 — side-effect
        from skills.registry import _default_registry
        assert "set_session_note" in _default_registry.get_all_skill_names()

    def test_get_session_note_registered(self):
        import skills.local.session_notes  # noqa: F401 — side-effect
        from skills.registry import _default_registry
        assert "get_session_note" in _default_registry.get_all_skill_names()
