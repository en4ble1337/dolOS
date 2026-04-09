"""Tests for the transcript search skill."""

from __future__ import annotations

import skills.local.memory as memory_skill


class _IndexNoHits:
    def search(self, query: str, limit: int = 10) -> list[dict]:
        return []


class _IndexWithHits:
    def search(self, query: str, limit: int = 10) -> list[dict]:
        return [{
            "session_id": "session-1",
            "entry_type": "assistant",
            "content": "The deployment happened after the backup completed.",
            "timestamp": "2026-04-09T12:00:00+00:00",
            "score": -1.23,
        }]


def setup_function() -> None:
    if hasattr(memory_skill, "set_transcript_index"):
        memory_skill.set_transcript_index(None)


def test_no_index_configured_returns_clear_error() -> None:
    result = memory_skill.search_transcripts("backup")

    assert "not available" in result.lower()


def test_no_hits_returns_clear_no_results_message() -> None:
    memory_skill.set_transcript_index(_IndexNoHits())

    result = memory_skill.search_transcripts("backup")

    assert "no transcripts found" in result.lower()


def test_hits_return_formatted_output() -> None:
    memory_skill.set_transcript_index(_IndexWithHits())

    result = memory_skill.search_transcripts("backup")

    assert "session-1" in result
    assert "assistant" in result
    assert "2026-04-09T12:00:00+00:00" in result
    assert "deployment happened" in result
