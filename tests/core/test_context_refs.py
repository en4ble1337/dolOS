"""Tests for @-syntax context reference expansion (Gap H4)."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.context_refs import expand_refs, _is_sensitive, _parse_file_arg


class TestIsSensitive:
    def test_ssh_path_blocked(self):
        assert _is_sensitive("/home/user/.ssh/id_rsa") is True

    def test_env_file_blocked(self):
        assert _is_sensitive(".env") is True

    def test_credentials_blocked(self):
        assert _is_sensitive("config/credentials.json") is True

    def test_normal_path_allowed(self):
        assert _is_sensitive("core/agent.py") is False

    def test_aws_blocked(self):
        assert _is_sensitive("/home/user/.aws/credentials") is True


class TestParseFileArg:
    def test_plain_path(self):
        path, rng = _parse_file_arg("core/agent.py")
        assert path == "core/agent.py"
        assert rng is None

    def test_range_suffix(self):
        path, rng = _parse_file_arg("core/agent.py:10-25")
        assert path == "core/agent.py"
        assert rng == (10, 25)

    def test_empty_arg(self):
        path, rng = _parse_file_arg("")
        assert path == ""
        assert rng is None


class TestExpandRefs:
    def test_no_refs_passthrough(self):
        prompt = "Hello, how are you today?"
        assert expand_refs(prompt) == prompt

    def test_email_not_expanded(self):
        """Bare email addresses must not be treated as @refs."""
        prompt = "contact user@example.com for help"
        result = expand_refs(prompt)
        assert result == prompt

    # --- @file ---

    def test_file_expansion(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world\n")
        prompt = f"check @file:{f}"
        result = expand_refs(prompt)
        assert "hello world" in result
        assert "```" in result

    def test_file_line_range(self, tmp_path: Path):
        f = tmp_path / "multi.txt"
        f.write_text("line1\nline2\nline3\nline4\nline5\n")
        prompt = f"@file:{f}:2-3"
        result = expand_refs(prompt)
        assert "line2" in result
        assert "line4" not in result

    def test_file_not_found(self):
        result = expand_refs("@file:/nonexistent/path/file.txt")
        assert "not found" in result

    def test_sensitive_file_blocked(self):
        result = expand_refs("@file:.env")
        assert "blocked" in result

    def test_binary_file_skipped(self, tmp_path: Path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\x03binary data\x00")
        result = expand_refs(f"@file:{f}")
        assert "binary file skipped" in result

    # --- @folder ---

    def test_folder_expansion(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("file A")
        (tmp_path / "b.txt").write_text("file B")
        result = expand_refs(f"@folder:{tmp_path}")
        assert "file A" in result
        assert "file B" in result

    def test_folder_not_a_dir(self, tmp_path: Path):
        f = tmp_path / "plain.txt"
        f.write_text("x")
        result = expand_refs(f"@folder:{f}")
        assert "not a directory" in result

    def test_sensitive_folder_blocked(self):
        result = expand_refs("@folder:.ssh/")
        assert "blocked" in result

    # --- @diff / @staged ---

    def test_diff_calls_git(self):
        with patch("core.context_refs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="diff output\n", stderr="")
            result = expand_refs("please review @diff")
        assert "diff output" in result
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][:2] == ["git", "diff"]

    def test_staged_calls_git(self):
        with patch("core.context_refs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="staged diff\n", stderr="")
            result = expand_refs("@staged")
        assert "staged diff" in result
        assert "--staged" in mock_run.call_args[0][0]

    def test_git_not_found(self):
        with patch("core.context_refs.subprocess.run", side_effect=FileNotFoundError):
            result = expand_refs("@diff")
        assert "git not found" in result

    # --- @git:N ---

    def test_git_log(self):
        with patch("core.context_refs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="commit abc\n", stderr="")
            result = expand_refs("context: @git:3")
        assert "commit abc" in result
        args = mock_run.call_args[0][0]
        assert "-3" in args

    def test_git_log_default_n(self):
        """@git without a number defaults to 5."""
        with patch("core.context_refs.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="log\n", stderr="")
            expand_refs("@git:")
        args = mock_run.call_args[0][0]
        assert "-5" in args

    # --- @url ---

    def test_url_fetch(self):
        with patch("core.context_refs.urllib.request.urlopen") as mock_open:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=MagicMock(
                read=MagicMock(return_value=b"<html><body>Hello page</body></html>")
            ))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_cm
            result = expand_refs("@url:https://example.com")
        assert "Hello page" in result

    # --- Limits ---

    def test_hard_limit_blocks_expansion(self, tmp_path: Path):
        """Expansion stops when injected chars >= hard limit."""
        large = "x" * 100
        f = tmp_path / "big.txt"
        f.write_text(large)
        # context_window=100 → hard_limit=50 chars
        result = expand_refs(f"@file:{f} @file:{f}", context_window=100)
        assert "hard limit reached" in result

    def test_soft_limit_warns(self, tmp_path: Path):
        """A warning is prepended when injected chars cross the soft limit."""
        large = "a" * 500
        f = tmp_path / "medium.txt"
        f.write_text(large)
        # context_window=1000 → soft=250
        result = expand_refs(f"@file:{f}", context_window=1000)
        assert "WARNING" in result

    # --- Multiple refs in one prompt ---

    def test_multiple_refs_in_prompt(self, tmp_path: Path):
        f1 = tmp_path / "f1.txt"
        f2 = tmp_path / "f2.txt"
        f1.write_text("content one")
        f2.write_text("content two")
        result = expand_refs(f"first @file:{f1} second @file:{f2}")
        assert "content one" in result
        assert "content two" in result
