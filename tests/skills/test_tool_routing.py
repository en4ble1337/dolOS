"""Tests for dynamic tool routing via SkillRegistry.get_relevant_schemas (Gap 4).

TDD Red phase — these tests MUST FAIL before get_relevant_schemas() is added.
"""

from __future__ import annotations

import pytest

from skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_registry_with_n_skills(n: int, *, extra_skills: list[tuple] | None = None) -> SkillRegistry:
    """Create a SkillRegistry with *n* dummy skills plus optional named extras."""
    reg = SkillRegistry()
    for i in range(n):
        def _fn(x: str = "") -> str:
            return x
        reg.register(f"skill_{i}", f"Description of skill number {i}", _fn)
    if extra_skills:
        for name, description in extra_skills:
            def _fn2(x: str = "") -> str:
                return x
            reg.register(name, description, _fn2)
    return reg


# ---------------------------------------------------------------------------
# Method existence
# ---------------------------------------------------------------------------

class TestGetRelevantSchemasInterface:
    def test_method_exists_on_registry(self):
        reg = SkillRegistry()
        assert hasattr(reg, "get_relevant_schemas")
        assert callable(reg.get_relevant_schemas)

    def test_returns_list_of_dicts(self):
        reg = _make_registry_with_n_skills(5)
        result = reg.get_relevant_schemas("some query")
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)

    def test_accepts_max_tools_param(self):
        reg = _make_registry_with_n_skills(5)
        result = reg.get_relevant_schemas("query", max_tools=3)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Behaviour when registry has ≤ 10 tools (routing disabled)
# ---------------------------------------------------------------------------

class TestGetRelevantSchemasSmallRegistry:
    def test_returns_all_when_10_or_fewer_tools(self):
        """When the registry has ≤ 10 skills, return all schemas unfiltered."""
        reg = _make_registry_with_n_skills(10)
        result = reg.get_relevant_schemas("anything")
        assert len(result) == 10

    def test_returns_all_when_registry_empty(self):
        reg = SkillRegistry()
        result = reg.get_relevant_schemas("anything")
        assert result == []

    def test_returns_all_when_exactly_1_skill(self):
        reg = _make_registry_with_n_skills(1)
        result = reg.get_relevant_schemas("query")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Behaviour when registry has > 10 tools (routing active)
# ---------------------------------------------------------------------------

class TestGetRelevantSchemasLargeRegistry:
    def test_limits_results_to_max_tools_when_over_threshold(self):
        reg = _make_registry_with_n_skills(15)
        result = reg.get_relevant_schemas("query about skill", max_tools=10)
        assert len(result) <= 10

    def test_default_max_tools_is_10(self):
        reg = _make_registry_with_n_skills(15)
        result = reg.get_relevant_schemas("query")
        assert len(result) <= 10

    def test_relevant_skill_ranks_higher(self):
        """A skill whose name matches the query keyword should be in results."""
        reg = _make_registry_with_n_skills(
            10,
            extra_skills=[("read_file", "Read file contents from disk")],
        )
        # Registry now has 11 tools → routing activates
        result = reg.get_relevant_schemas("read file from disk", max_tools=5)
        names = [s["name"] for s in result]
        assert "read_file" in names

    def test_skill_matching_description_keyword_included(self):
        """A skill whose description matches the query keyword should be ranked up."""
        reg = _make_registry_with_n_skills(
            10,
            extra_skills=[("exec_bash", "Execute a bash shell command")],
        )
        result = reg.get_relevant_schemas("bash shell", max_tools=5)
        names = [s["name"] for s in result]
        assert "exec_bash" in names

    def test_no_duplicates_in_result(self):
        reg = _make_registry_with_n_skills(15)
        result = reg.get_relevant_schemas("skill description query")
        names = [s["name"] for s in result]
        assert len(names) == len(set(names))

    def test_result_schemas_have_name_key(self):
        reg = _make_registry_with_n_skills(15)
        result = reg.get_relevant_schemas("skill")
        for schema in result:
            assert "name" in schema

    def test_max_tools_larger_than_registry_returns_all(self):
        """max_tools > registry size → return all (no truncation)."""
        reg = _make_registry_with_n_skills(15)
        result = reg.get_relevant_schemas("query", max_tools=100)
        assert len(result) == 15
