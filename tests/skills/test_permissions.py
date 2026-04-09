"""Tests for PermissionPolicy and filter_schemas (Gap 1).

TDD Red phase — these tests MUST FAIL before skills/permissions.py exists.
They define the expected interface for the permission layer.
"""

from __future__ import annotations

import pytest

from skills.permissions import PermissionPolicy, filter_schemas


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCHEMAS = [
    {"name": "read_file", "description": "Read a file"},
    {"name": "write_file", "description": "Write a file"},
    {"name": "run_command", "description": "Run a shell command"},
    {"name": "delete_file", "description": "Delete a file"},
    {"name": "list_directory", "description": "List directory contents"},
]


# ---------------------------------------------------------------------------
# PermissionPolicy dataclass
# ---------------------------------------------------------------------------

class TestPermissionPolicyDefaults:
    def test_deny_names_defaults_empty(self):
        policy = PermissionPolicy()
        assert policy.deny_names == set()

    def test_deny_prefixes_defaults_empty(self):
        policy = PermissionPolicy()
        assert policy.deny_prefixes == set()

    def test_allow_only_defaults_none(self):
        policy = PermissionPolicy()
        assert policy.allow_only is None

    def test_can_set_deny_names(self):
        policy = PermissionPolicy(deny_names={"run_command"})
        assert "run_command" in policy.deny_names

    def test_can_set_deny_prefixes(self):
        policy = PermissionPolicy(deny_prefixes={"write_", "delete_"})
        assert "write_" in policy.deny_prefixes

    def test_can_set_allow_only(self):
        policy = PermissionPolicy(allow_only={"read_file"})
        assert policy.allow_only == {"read_file"}


# ---------------------------------------------------------------------------
# filter_schemas — passthrough (empty policy)
# ---------------------------------------------------------------------------

class TestFilterSchemasPassthrough:
    def test_empty_policy_returns_all(self):
        policy = PermissionPolicy()
        result = filter_schemas(SCHEMAS, policy)
        assert result == SCHEMAS

    def test_empty_schema_list_returns_empty(self):
        policy = PermissionPolicy(deny_names={"read_file"})
        result = filter_schemas([], policy)
        assert result == []


# ---------------------------------------------------------------------------
# filter_schemas — allow_only
# ---------------------------------------------------------------------------

class TestFilterSchemasAllowOnly:
    def test_allow_only_single_name(self):
        policy = PermissionPolicy(allow_only={"read_file"})
        result = filter_schemas(SCHEMAS, policy)
        assert [s["name"] for s in result] == ["read_file"]

    def test_allow_only_multiple_names(self):
        policy = PermissionPolicy(allow_only={"read_file", "list_directory"})
        result = filter_schemas(SCHEMAS, policy)
        names = {s["name"] for s in result}
        assert names == {"read_file", "list_directory"}

    def test_allow_only_empty_set_blocks_all(self):
        policy = PermissionPolicy(allow_only=set())
        result = filter_schemas(SCHEMAS, policy)
        assert result == []

    def test_allow_only_name_not_in_list_is_blocked(self):
        policy = PermissionPolicy(allow_only={"read_file"})
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "run_command" not in names
        assert "write_file" not in names
        assert "delete_file" not in names

    def test_gate_allow_only_blocks_run_command(self):
        """Phase 3 → 4 gate: PermissionPolicy(allow_only={"read_file"}) must block run_command."""
        policy = PermissionPolicy(allow_only={"read_file"})
        result = filter_schemas(SCHEMAS, policy)
        assert not any(s["name"] == "run_command" for s in result)
        assert any(s["name"] == "read_file" for s in result)


# ---------------------------------------------------------------------------
# filter_schemas — deny_names
# ---------------------------------------------------------------------------

class TestFilterSchemasDenyNames:
    def test_deny_names_removes_exact_match(self):
        policy = PermissionPolicy(deny_names={"run_command"})
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "run_command" not in names

    def test_deny_names_preserves_others(self):
        policy = PermissionPolicy(deny_names={"run_command"})
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "read_file" in names
        assert "write_file" in names

    def test_deny_names_multiple(self):
        policy = PermissionPolicy(deny_names={"run_command", "delete_file"})
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "run_command" not in names
        assert "delete_file" not in names

    def test_deny_names_nonexistent_name_is_noop(self):
        policy = PermissionPolicy(deny_names={"nonexistent_tool"})
        result = filter_schemas(SCHEMAS, policy)
        assert result == SCHEMAS


# ---------------------------------------------------------------------------
# filter_schemas — deny_prefixes
# ---------------------------------------------------------------------------

class TestFilterSchemasDenyPrefixes:
    def test_deny_prefix_removes_matching(self):
        policy = PermissionPolicy(deny_prefixes={"write_"})
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "write_file" not in names

    def test_deny_prefix_multiple(self):
        policy = PermissionPolicy(deny_prefixes={"write_", "delete_"})
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "write_file" not in names
        assert "delete_file" not in names

    def test_deny_prefix_preserves_non_matching(self):
        policy = PermissionPolicy(deny_prefixes={"write_"})
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "read_file" in names
        assert "run_command" in names

    def test_deny_prefix_partial_match_only(self):
        """Only prefix, not suffix or substring match."""
        policy = PermissionPolicy(deny_prefixes={"file"})
        result = filter_schemas(SCHEMAS, policy)
        # read_file, write_file, delete_file don't START with "file"
        assert len(result) == len(SCHEMAS)


# ---------------------------------------------------------------------------
# filter_schemas — combined rules (allow_only + deny takes precedence)
# ---------------------------------------------------------------------------

class TestFilterSchemasCombined:
    def test_deny_names_applied_even_with_allow_only(self):
        """deny_names takes precedence even if name is in allow_only."""
        policy = PermissionPolicy(
            allow_only={"read_file", "run_command"},
            deny_names={"run_command"},
        )
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "run_command" not in names
        assert "read_file" in names

    def test_deny_prefixes_applied_even_with_allow_only(self):
        policy = PermissionPolicy(
            allow_only={"read_file", "write_file"},
            deny_prefixes={"write_"},
        )
        result = filter_schemas(SCHEMAS, policy)
        names = [s["name"] for s in result]
        assert "write_file" not in names
        assert "read_file" in names
