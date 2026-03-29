"""Tests for memory.static_loader.StaticFileLoader."""
import os
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, call, patch

import pytest

from memory.static_loader import StaticFileLoader


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_memory_mock(search_results: Optional[List[Dict[str, Any]]] = None) -> MagicMock:
    """Return a MagicMock that mimics MemoryManager."""
    mock = MagicMock()
    mock.search.return_value = search_results if search_results is not None else []
    return mock


def _make_loader(
    memory: Optional[MagicMock] = None,
    chunk_size: int = 400,
    overlap: int = 80,
) -> StaticFileLoader:
    if memory is None:
        memory = _make_memory_mock()
    return StaticFileLoader(memory=memory, chunk_size=chunk_size, overlap=overlap)


def _write_temp_file(content: str) -> str:
    """Write content to a temp file and return its path. Caller must delete."""
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# ---------------------------------------------------------------------------
# index_file: basic chunking and storage
# ---------------------------------------------------------------------------

def test_index_file_chunks_and_stores() -> None:
    """index_file should call add_memory once per chunk with correct metadata."""
    content = "Hello world.\n\nThis is a second paragraph.\n\nAnd a third."
    path = _write_temp_file(content)
    try:
        memory = _make_memory_mock(search_results=[])
        loader = _make_loader(memory=memory, chunk_size=400, overlap=80)

        count = loader.index_file(path, source_tag="user_profile")

        expected_chunks = loader._chunk_text(content)
        assert count == len(expected_chunks)
        assert count > 0
        assert memory.add_memory.call_count == count

        # Verify each call has the right metadata shape
        mtime = os.path.getmtime(path)
        for idx, c in enumerate(memory.add_memory.call_args_list):
            kwargs = c.kwargs if c.kwargs else {}
            args = c.args if c.args else ()

            # Support both positional and keyword calling styles
            text_arg = kwargs.get("text", args[0] if args else None)
            memory_type_arg = kwargs.get("memory_type", "semantic")
            importance_arg = kwargs.get("importance", None)
            metadata_arg = kwargs.get("metadata", {})

            assert memory_type_arg == "semantic"
            assert importance_arg == 0.6
            assert metadata_arg["source"] == "user_profile"
            assert metadata_arg["chunk_index"] == idx
            assert metadata_arg["mtime"] == pytest.approx(mtime, abs=1.0)
            assert metadata_arg["path"] == path
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# index_file: missing file
# ---------------------------------------------------------------------------

def test_index_file_skips_missing_file() -> None:
    """index_file should return 0 and not raise when the file does not exist."""
    memory = _make_memory_mock()
    loader = _make_loader(memory=memory)

    result = loader.index_file("/nonexistent/path/MISSING.md", source_tag="missing")

    assert result == 0
    memory.add_memory.assert_not_called()


# ---------------------------------------------------------------------------
# index_file: unchanged file (mtime matches stored)
# ---------------------------------------------------------------------------

def test_index_file_skips_unchanged_file() -> None:
    """index_file should return 0 when stored mtime matches current mtime."""
    path = _write_temp_file("Some content.\n\nMore content.")
    try:
        current_mtime = os.path.getmtime(path)
        # Simulate already-indexed result with matching mtime
        stored_result = [
            {
                "text": "Some content.",
                "score": 0.9,
                "metadata": {"source": "user_profile", "mtime": current_mtime},
                "timestamp": 0.0,
                "importance": 0.6,
                "similarity": 0.9,
            }
        ]
        memory = _make_memory_mock(search_results=stored_result)
        loader = _make_loader(memory=memory)

        result = loader.index_file(path, source_tag="user_profile")

        assert result == 0
        memory.add_memory.assert_not_called()
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# index_file: mtime changed → re-index
# ---------------------------------------------------------------------------

def test_index_file_reindexes_when_mtime_changed() -> None:
    """index_file should index when stored mtime differs from current mtime."""
    path = _write_temp_file("Updated content.\n\nNew paragraph here.")
    try:
        current_mtime = os.path.getmtime(path)
        old_mtime = current_mtime - 999.0  # clearly different
        stored_result = [
            {
                "text": "Old content.",
                "score": 0.9,
                "metadata": {"source": "user_profile", "mtime": old_mtime},
                "timestamp": 0.0,
                "importance": 0.6,
                "similarity": 0.9,
            }
        ]
        memory = _make_memory_mock(search_results=stored_result)
        loader = _make_loader(memory=memory)

        result = loader.index_file(path, source_tag="user_profile")

        assert result > 0
        assert memory.add_memory.call_count == result
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# _chunk_text: large paragraph splitting
# ---------------------------------------------------------------------------

def test_chunk_text_splits_large_paragraphs() -> None:
    """Each raw segment produced before overlap should respect chunk_size."""
    loader = _make_loader(chunk_size=50, overlap=10)

    # Single paragraph of 200 chars (4 × chunk_size)
    long_para = "A" * 200
    chunks = loader._chunk_text(long_para)

    assert len(chunks) > 1
    # After overlap is applied the chunks may be slightly larger than chunk_size,
    # but the *content* portion (excluding overlap prefix) must be <= chunk_size.
    # The first chunk has no prefix, so it must be exactly chunk_size (or less).
    assert len(chunks[0]) <= 50


def test_chunk_text_splits_multiple_large_paragraphs() -> None:
    """Paragraphs larger than chunk_size are each broken into sub-chunks."""
    loader = _make_loader(chunk_size=30, overlap=5)

    # Two paragraphs, each 90 chars → each should yield 3 sub-chunks
    text = ("B" * 90) + "\n\n" + ("C" * 90)
    chunks = loader._chunk_text(text)

    # Expect at least 4 chunks (could be more with overlap)
    assert len(chunks) >= 4


# ---------------------------------------------------------------------------
# _chunk_text: overlap verification
# ---------------------------------------------------------------------------

def test_chunk_text_overlap() -> None:
    """The last ``overlap`` chars of chunk N should appear at the start of chunk N+1."""
    overlap = 10
    chunk_size = 30
    loader = _make_loader(chunk_size=chunk_size, overlap=overlap)

    # Single long paragraph that will be split into multiple sub-chunks
    long_para = "".join(str(i % 10) for i in range(120))  # 120-char string
    chunks = loader._chunk_text(long_para)

    assert len(chunks) >= 2

    # The first chunk has no overlap prefix, so its content is the raw first segment.
    first_chunk = chunks[0]
    second_chunk = chunks[1]

    # The tail of the first chunk (up to overlap chars) should be a prefix of second.
    tail = first_chunk[-overlap:]
    assert second_chunk.startswith(tail), (
        f"Expected second chunk to start with '{tail}', got '{second_chunk[:overlap + 5]}'"
    )


def test_chunk_text_empty_input() -> None:
    """_chunk_text should return an empty list for empty/whitespace-only input."""
    loader = _make_loader()
    assert loader._chunk_text("") == []
    assert loader._chunk_text("   \n\n  ") == []


def test_chunk_text_single_short_paragraph() -> None:
    """A single paragraph shorter than chunk_size should be returned as one chunk."""
    loader = _make_loader(chunk_size=200, overlap=20)
    text = "Short paragraph."
    chunks = loader._chunk_text(text)
    assert chunks == ["Short paragraph."]


# ---------------------------------------------------------------------------
# _get_stored_mtime: integration with memory.search
# ---------------------------------------------------------------------------

def test_get_stored_mtime_returns_none_when_no_results() -> None:
    """_get_stored_mtime should return None when search yields no results."""
    memory = _make_memory_mock(search_results=[])
    loader = _make_loader(memory=memory)
    result = loader._get_stored_mtime("some_tag")
    assert result is None


def test_get_stored_mtime_returns_mtime_from_metadata() -> None:
    """_get_stored_mtime should extract mtime from the first result's metadata."""
    expected_mtime = 1711234567.89
    search_results = [
        {
            "text": "chunk text",
            "score": 0.9,
            "metadata": {"source": "some_tag", "mtime": expected_mtime},
            "timestamp": 0.0,
            "importance": 0.6,
            "similarity": 0.9,
        }
    ]
    memory = _make_memory_mock(search_results=search_results)
    loader = _make_loader(memory=memory)
    result = loader._get_stored_mtime("some_tag")
    assert result == pytest.approx(expected_mtime)


def test_get_stored_mtime_passes_correct_filter() -> None:
    """_get_stored_mtime should pass filter_metadata={"source": source_tag}."""
    memory = _make_memory_mock(search_results=[])
    loader = _make_loader(memory=memory)
    loader._get_stored_mtime("long_term_decisions")

    memory.search.assert_called_once()
    _, kwargs = memory.search.call_args
    assert kwargs.get("filter_metadata") == {"source": "long_term_decisions"}
    assert kwargs.get("limit") == 1
    assert kwargs.get("memory_type") == "semantic"


def test_get_stored_mtime_handles_search_exception() -> None:
    """_get_stored_mtime should return None if memory.search raises."""
    memory = MagicMock()
    memory.search.side_effect = RuntimeError("connection error")
    loader = _make_loader(memory=memory)
    result = loader._get_stored_mtime("any_tag")
    assert result is None
