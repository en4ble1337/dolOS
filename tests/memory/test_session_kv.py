"""Tests for memory/session_kv.py (Gap 5)."""

import json
import pytest
from pathlib import Path

from memory.session_kv import SessionKVStore


@pytest.fixture
def store(tmp_path):
    return SessionKVStore(data_dir=str(tmp_path / "session_kv"))


class TestSetAndGet:
    def test_set_then_get(self, store):
        store.set("s1", "lang", "Python")
        assert store.get("s1", "lang") == "Python"

    def test_get_missing_key_returns_none(self, store):
        assert store.get("s1", "nonexistent") is None

    def test_get_missing_session_returns_none(self, store):
        assert store.get("new_session", "key") is None

    def test_overwrite_existing(self, store):
        store.set("s1", "lang", "Python")
        store.set("s1", "lang", "Go")
        assert store.get("s1", "lang") == "Go"


class TestDelete:
    def test_delete_existing(self, store):
        store.set("s1", "k", "v")
        assert store.delete("s1", "k") is True
        assert store.get("s1", "k") is None

    def test_delete_missing_returns_false(self, store):
        assert store.delete("s1", "nope") is False


class TestGetAll:
    def test_empty_session(self, store):
        assert store.get_all("empty") == {}

    def test_multiple_keys(self, store):
        store.set("s1", "a", "1")
        store.set("s1", "b", "2")
        result = store.get_all("s1")
        assert result == {"a": "1", "b": "2"}

    def test_get_all_returns_copy(self, store):
        store.set("s1", "x", "y")
        copy = store.get_all("s1")
        copy["new"] = "should not appear"
        assert store.get("s1", "new") is None


class TestClear:
    def test_clear_removes_all(self, store):
        store.set("s1", "a", "1")
        store.set("s1", "b", "2")
        store.clear("s1")
        assert store.get_all("s1") == {}


class TestPersistence:
    def test_persists_across_instances(self, tmp_path):
        data_dir = str(tmp_path / "kv")
        store1 = SessionKVStore(data_dir=data_dir)
        store1.set("s1", "key", "value")

        store2 = SessionKVStore(data_dir=data_dir)
        assert store2.get("s1", "key") == "value"

    def test_json_file_created(self, tmp_path):
        data_dir = tmp_path / "kv"
        store = SessionKVStore(data_dir=str(data_dir))
        store.set("mysession", "x", "y")
        assert (data_dir / "mysession.json").exists()


class TestFormatForPrompt:
    def test_empty_returns_empty_string(self, store):
        assert store.format_for_prompt("empty") == ""

    def test_non_empty_contains_xml_tags(self, store):
        store.set("s1", "lang", "Python")
        output = store.format_for_prompt("s1")
        assert "<session_memory>" in output
        assert "</session_memory>" in output
        assert "lang: Python" in output

    def test_multiple_keys_sorted(self, store):
        store.set("s1", "z_key", "last")
        store.set("s1", "a_key", "first")
        output = store.format_for_prompt("s1")
        assert output.index("a_key") < output.index("z_key")


class TestIsolation:
    def test_different_sessions_are_isolated(self, store):
        store.set("sess_a", "key", "alpha")
        store.set("sess_b", "key", "beta")
        assert store.get("sess_a", "key") == "alpha"
        assert store.get("sess_b", "key") == "beta"
