"""Tests for TranscriptStore (Gap 13).

TDD Red phase — these tests MUST FAIL before storage/transcripts.py exists.
They define the expected interface: append-only JSONL, session listing,
session reading, and correct entry structure.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from storage.transcripts import TranscriptStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """TranscriptStore pointed at a temp directory."""
    return TranscriptStore(data_dir=str(tmp_path / "transcripts"))


# ---------------------------------------------------------------------------
# Append creates JSONL file
# ---------------------------------------------------------------------------

class TestAppendCreatesFile:
    def test_append_creates_jsonl_file(self, store, tmp_path):
        store.append("sess-1", "user", content="Hello")
        transcript_dir = tmp_path / "transcripts"
        jsonl_file = transcript_dir / "sess-1.jsonl"
        assert jsonl_file.exists(), "JSONL file should be created on first append"

    def test_append_writes_valid_json_per_line(self, store, tmp_path):
        store.append("sess-1", "user", content="Hello")
        transcript_dir = tmp_path / "transcripts"
        lines = (transcript_dir / "sess-1.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert isinstance(parsed, dict)

    def test_append_multiple_entries_each_on_own_line(self, store, tmp_path):
        store.append("sess-1", "user", content="Hello")
        store.append("sess-1", "assistant", content="Hi there!")
        store.append("sess-1", "user", content="How are you?")
        transcript_dir = tmp_path / "transcripts"
        lines = (transcript_dir / "sess-1.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # each line must be valid JSON


# ---------------------------------------------------------------------------
# Entry structure
# ---------------------------------------------------------------------------

class TestEntryStructure:
    def test_entry_has_type(self, store, tmp_path):
        store.append("sess-1", "user", content="Hello")
        data = json.loads((tmp_path / "transcripts" / "sess-1.jsonl").read_text().strip())
        assert data["type"] == "user"

    def test_entry_has_session_id(self, store, tmp_path):
        store.append("sess-1", "user", content="Hello")
        data = json.loads((tmp_path / "transcripts" / "sess-1.jsonl").read_text().strip())
        assert data["session_id"] == "sess-1"

    def test_entry_has_timestamp(self, store, tmp_path):
        store.append("sess-1", "user", content="Hello")
        data = json.loads((tmp_path / "transcripts" / "sess-1.jsonl").read_text().strip())
        assert "ts" in data
        # Should be a non-empty ISO 8601 string
        assert isinstance(data["ts"], str)
        assert len(data["ts"]) >= 19  # "YYYY-MM-DDTHH:MM:SS"

    def test_entry_payload_preserved(self, store, tmp_path):
        store.append("sess-1", "tool_call", name="run_command", arguments={"command": "ls"})
        data = json.loads((tmp_path / "transcripts" / "sess-1.jsonl").read_text().strip())
        assert data["name"] == "run_command"
        assert data["arguments"] == {"command": "ls"}

    def test_all_entry_types_accepted(self, store, tmp_path):
        for entry_type in ("user", "assistant", "tool_call", "tool_result"):
            store.append("sess-1", entry_type, content="data")
        lines = (tmp_path / "transcripts" / "sess-1.jsonl").read_text().strip().split("\n")
        types = [json.loads(ln)["type"] for ln in lines]
        assert set(types) == {"user", "assistant", "tool_call", "tool_result"}


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------

class TestSessionIsolation:
    def test_different_sessions_write_separate_files(self, store, tmp_path):
        store.append("sess-A", "user", content="Hello from A")
        store.append("sess-B", "user", content="Hello from B")
        transcript_dir = tmp_path / "transcripts"
        assert (transcript_dir / "sess-A.jsonl").exists()
        assert (transcript_dir / "sess-B.jsonl").exists()

    def test_sessions_do_not_cross_contaminate(self, store, tmp_path):
        store.append("sess-A", "user", content="msg A")
        store.append("sess-B", "assistant", content="msg B")
        lines_a = (tmp_path / "transcripts" / "sess-A.jsonl").read_text().strip().split("\n")
        lines_b = (tmp_path / "transcripts" / "sess-B.jsonl").read_text().strip().split("\n")
        assert len(lines_a) == 1
        assert len(lines_b) == 1
        assert json.loads(lines_a[0])["session_id"] == "sess-A"
        assert json.loads(lines_b[0])["session_id"] == "sess-B"


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_list_sessions_returns_known_sessions(self, store):
        store.append("sess-1", "user", content="Hello")
        store.append("sess-2", "user", content="Hello")
        sessions = store.list_sessions()
        session_ids = {s["session_id"] for s in sessions}
        assert "sess-1" in session_ids
        assert "sess-2" in session_ids

    def test_list_sessions_empty_when_no_transcripts(self, store):
        sessions = store.list_sessions()
        assert sessions == []

    def test_list_sessions_each_entry_has_session_id(self, store):
        store.append("sess-1", "user", content="Hello")
        sessions = store.list_sessions()
        assert all("session_id" in s for s in sessions)

    def test_list_sessions_each_entry_has_entry_count(self, store):
        store.append("sess-1", "user", content="Hello")
        store.append("sess-1", "assistant", content="Hi")
        sessions = store.list_sessions()
        sess = next(s for s in sessions if s["session_id"] == "sess-1")
        assert sess.get("entry_count") == 2


# ---------------------------------------------------------------------------
# read_session
# ---------------------------------------------------------------------------

class TestReadSession:
    def test_read_session_returns_entries_in_order(self, store):
        store.append("sess-1", "user", content="first")
        store.append("sess-1", "assistant", content="second")
        store.append("sess-1", "user", content="third")
        entries = store.read_session("sess-1")
        assert len(entries) == 3
        assert entries[0]["content"] == "first"
        assert entries[1]["content"] == "second"
        assert entries[2]["content"] == "third"

    def test_read_session_missing_returns_empty_list(self, store):
        entries = store.read_session("nonexistent-session")
        assert entries == []

    def test_read_session_entries_are_dicts(self, store):
        store.append("sess-1", "user", content="Hello")
        entries = store.read_session("sess-1")
        assert all(isinstance(e, dict) for e in entries)

    def test_read_session_preserves_all_fields(self, store):
        store.append("sess-1", "tool_call", name="read_file", arguments={"path": "/tmp/x"})
        entries = store.read_session("sess-1")
        assert entries[0]["type"] == "tool_call"
        assert entries[0]["name"] == "read_file"
        assert entries[0]["arguments"] == {"path": "/tmp/x"}
        assert "ts" in entries[0]
        assert "session_id" in entries[0]


# ---------------------------------------------------------------------------
# Transcript index integration
# ---------------------------------------------------------------------------

class TestTranscriptIndexIntegration:
    def test_append_calls_append_entry_when_index_configured(self, tmp_path):
        transcript_index = MagicMock()
        store = TranscriptStore(
            data_dir=str(tmp_path / "transcripts"),
            transcript_index=transcript_index,
        )

        store.append("sess-1", "user", content="Hello transcript index")

        transcript_index.append_entry.assert_called_once()
        session_id, entry = transcript_index.append_entry.call_args.args
        assert session_id == "sess-1"
        assert entry["type"] == "user"
        assert entry["content"] == "Hello transcript index"

    def test_append_still_succeeds_if_indexing_raises(self, tmp_path):
        transcript_index = MagicMock()
        transcript_index.append_entry.side_effect = RuntimeError("index failed")
        store = TranscriptStore(
            data_dir=str(tmp_path / "transcripts"),
            transcript_index=transcript_index,
        )

        store.append("sess-1", "assistant", content="still written")

        entries = store.read_session("sess-1")
        assert len(entries) == 1
        assert entries[0]["content"] == "still written"
