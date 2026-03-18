"""Tests that local skill modules auto-register into the global default registry."""

import skills.local.filesystem  # noqa: F401 — registers read_file, write_file
import skills.local.system  # noqa: F401 — registers run_command

from skills.registry import _default_registry


class TestLocalSkillsAutoLoad:
    def test_read_file_registered(self) -> None:
        assert "read_file" in _default_registry.get_all_skill_names()

    def test_write_file_registered(self) -> None:
        assert "write_file" in _default_registry.get_all_skill_names()

    def test_run_command_registered(self) -> None:
        assert "run_command" in _default_registry.get_all_skill_names()
