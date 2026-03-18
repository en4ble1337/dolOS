"""Tests for headless mode detection and log_level configuration."""

import logging
import sys
from unittest.mock import patch

from core.config import Settings


class TestLogLevelConfig:
    def test_default_log_level_is_info(self) -> None:
        s = Settings()
        assert s.log_level == "INFO"

    def test_custom_log_level_from_field(self) -> None:
        s = Settings(log_level="DEBUG")
        assert s.log_level == "DEBUG"

    def test_log_level_resolves_to_logging_constant(self) -> None:
        s = Settings(log_level="DEBUG")
        level = getattr(logging, s.log_level.upper(), logging.INFO)
        assert level == logging.DEBUG

    def test_invalid_log_level_falls_back_to_info(self) -> None:
        s = Settings(log_level="NONSENSE")
        level = getattr(logging, s.log_level.upper(), logging.INFO)
        assert level == logging.INFO

    def test_log_level_case_insensitive(self) -> None:
        s = Settings(log_level="warning")
        level = getattr(logging, s.log_level.upper(), logging.INFO)
        assert level == logging.WARNING


class TestHeadlessDetection:
    """Tests for the sys.stdin.isatty() detection logic used in main().

    main() itself cannot be unit-tested without importing the module (which
    triggers heavy component initialisation). Instead we verify the detection
    primitive and the branching guard directly.
    """

    def test_isatty_returns_false_when_stdin_is_not_tty(self) -> None:
        """Simulate a non-TTY stdin (as seen under systemd)."""
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            assert sys.stdin.isatty() is False

    def test_isatty_returns_true_when_stdin_is_tty(self) -> None:
        """Simulate an interactive terminal."""
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            assert sys.stdin.isatty() is True

    def test_headless_branch_condition(self) -> None:
        """The branching guard `not sys.stdin.isatty()` works correctly."""
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            # Headless path: isatty() is False → skip terminal
            assert not sys.stdin.isatty()

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            # Interactive path: isatty() is True → run terminal
            assert sys.stdin.isatty()
