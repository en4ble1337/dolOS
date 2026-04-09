"""Tests for Phase F transcript indexing and transcript search."""

from __future__ import annotations

import importlib
import json
from pathlib import Path


def _make_index(tmp_path):
    module = importlib.import_module("memory.transcript_index")
    index = module.TranscriptIndex(db_path=str(tmp_path / "transcript_index.db"))
    index.initialize()
    return index


def _write_jsonl(path: Path, entries: list[object]) -> None:
    lines = []
    for entry in entries:
        if isinstance(entry, str):
            lines.append(entry)
        else:
            lines.append(json.dumps(entry))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_append_entry_indexes_single_transcript_entry(tmp_path) -> None:
    index = _make_index(tmp_path)

    index.append_entry("session-1", {
        "ts": "2026-04-09T12:00:00+00:00",
        "type": "user",
        "content": "Remember that the API port is 8080.",
    })

    results = index.search("8080")

    assert len(results) == 1
    assert results[0]["session_id"] == "session-1"
    assert results[0]["entry_type"] == "user"
    assert "8080" in results[0]["content"]
    assert results[0]["timestamp"] == "2026-04-09T12:00:00+00:00"
    assert "score" in results[0]


def test_search_returns_hits_across_sessions(tmp_path) -> None:
    index = _make_index(tmp_path)

    index.append_entry("session-a", {
        "ts": "2026-04-09T12:00:00+00:00",
        "type": "user",
        "content": "Project atlas needs a schema migration.",
    })
    index.append_entry("session-b", {
        "ts": "2026-04-09T12:01:00+00:00",
        "type": "assistant",
        "content": "Atlas migration should happen after the backup.",
    })

    results = index.search("atlas")

    assert {result["session_id"] for result in results} == {"session-a", "session-b"}


def test_index_all_bulk_indexes_existing_jsonl_files(tmp_path) -> None:
    index = _make_index(tmp_path)
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()

    _write_jsonl(transcripts_dir / "session-a.jsonl", [
        {
            "ts": "2026-04-09T12:00:00+00:00",
            "type": "user",
            "session_id": "session-a",
            "content": "Need to revisit the backup policy.",
        },
        {
            "ts": "2026-04-09T12:00:10+00:00",
            "type": "assistant",
            "session_id": "session-a",
            "content": "The backup policy should keep seven daily snapshots.",
        },
    ])
    _write_jsonl(transcripts_dir / "session-b.jsonl", [
        {
            "ts": "2026-04-09T12:01:00+00:00",
            "type": "tool_result",
            "session_id": "session-b",
            "content": "backup-policy.md updated successfully",
        }
    ])

    indexed = index.index_all(transcripts_dir)
    results = index.search("backup")

    assert indexed == 3
    assert len(results) == 3


def test_index_session_does_not_duplicate_already_indexed_rows(tmp_path) -> None:
    index = _make_index(tmp_path)
    jsonl_path = tmp_path / "session-1.jsonl"
    _write_jsonl(jsonl_path, [
        {
            "ts": "2026-04-09T12:00:00+00:00",
            "type": "user",
            "session_id": "session-1",
            "content": "Need to deploy atlas today.",
        }
    ])

    first_count = index.index_session("session-1", jsonl_path)
    second_count = index.index_session("session-1", jsonl_path)

    _write_jsonl(jsonl_path, [
        {
            "ts": "2026-04-09T12:00:00+00:00",
            "type": "user",
            "session_id": "session-1",
            "content": "Need to deploy atlas today.",
        },
        {
            "ts": "2026-04-09T12:05:00+00:00",
            "type": "assistant",
            "session_id": "session-1",
            "content": "Atlas deploy completed successfully.",
        },
    ])

    third_count = index.index_session("session-1", jsonl_path)
    results = index.search("atlas")

    assert first_count == 1
    assert second_count == 0
    assert third_count == 1
    assert len(results) == 2


def test_malformed_json_line_is_skipped(tmp_path) -> None:
    index = _make_index(tmp_path)
    jsonl_path = tmp_path / "session-1.jsonl"
    _write_jsonl(jsonl_path, [
        {
            "ts": "2026-04-09T12:00:00+00:00",
            "type": "user",
            "session_id": "session-1",
            "content": "Need to inspect the release checklist.",
        },
        '{"ts": "broken"',
        {
            "ts": "2026-04-09T12:01:00+00:00",
            "type": "assistant",
            "session_id": "session-1",
            "content": "The release checklist is in docs/release.md.",
        },
    ])

    indexed = index.index_session("session-1", jsonl_path)
    repeat = index.index_session("session-1", jsonl_path)
    results = index.search("checklist")

    assert indexed == 2
    assert repeat == 0
    assert len(results) == 2


def test_tool_call_entries_are_searchable(tmp_path) -> None:
    index = _make_index(tmp_path)

    index.append_entry("session-1", {
        "ts": "2026-04-09T12:00:00+00:00",
        "type": "tool_call",
        "name": "read_file",
        "arguments": {"path": "docs/release-checklist.md"},
    })

    results = index.search("read_file")

    assert len(results) == 1
    assert results[0]["entry_type"] == "tool_call"
    assert "read_file" in results[0]["content"]


def test_search_limit_is_respected(tmp_path) -> None:
    index = _make_index(tmp_path)

    for i in range(5):
        index.append_entry("session-1", {
            "ts": f"2026-04-09T12:00:0{i}+00:00",
            "type": "assistant",
            "content": f"Needle result {i}",
        })

    results = index.search("needle", limit=2)

    assert len(results) == 2
