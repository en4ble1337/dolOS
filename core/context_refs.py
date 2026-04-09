"""@-syntax context reference expansion for the terminal channel (Gap H4).

Users can inject external content inline by prefixing tokens with ``@``:

    @file:path/to/file.py          — full file contents
    @file:main.py:10-25            — line range slice
    @folder:path/                  — all files in directory
    @diff                          — git diff (unstaged)
    @staged                        — git diff --staged
    @git:N                         — last N commits (git log -N -p)
    @url:https://...               — web page plain-text content

Safety:
- Sensitive paths (.ssh/, .env, credentials, id_rsa, id_ed25519) are blocked.
- Binary files are skipped.
- Injected content is measured in chars (≈ tokens * 4).
- Soft limit at 25% of context_window: expansion continues but a warning is
  prepended so the agent knows the context is large.
- Hard limit at 50%: further expansions are replaced with a notice.
"""

import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# Matches @type or @type:arg, but NOT plain email addresses (foo@bar.com)
# Anchored to word boundary or start — the @ must follow whitespace or be at start.
REF_PATTERN = re.compile(
    r"(?:^|(?<=\s))"                      # start of string or preceded by whitespace
    r"@(file|folder|diff|staged|git|url)"  # type token
    r"(?::([^\s]*))?",                     # optional :arg (no whitespace inside)
    re.MULTILINE,
)

BLOCKED_PATTERNS = [
    ".ssh/",
    ".env",
    "credentials",
    "id_rsa",
    "id_ed25519",
    ".aws/",
    "secrets",
]

SOFT_LIMIT_RATIO = 0.25  # warn, but continue
HARD_LIMIT_RATIO = 0.50  # block further expansion


def _is_sensitive(path: str) -> bool:
    lower = path.replace("\\", "/").lower()
    return any(pat in lower for pat in BLOCKED_PATTERNS)


def _is_binary(data: bytes) -> bool:
    """Detect binary files by looking for null bytes in the first 8 KB."""
    return b"\x00" in data[:8192]


def _read_file(path_str: str, line_range: Optional[tuple[int, int]] = None) -> str:
    """Read a file, optionally sliced to a line range (1-indexed, inclusive)."""
    try:
        p = Path(path_str)
        raw = p.read_bytes()
        if _is_binary(raw):
            return f"[binary file skipped: {path_str}]"
        text = raw.decode("utf-8", errors="replace")
        if line_range:
            lines = text.splitlines(keepends=True)
            start, end = line_range
            sliced = lines[start - 1 : end]
            text = "".join(sliced)
        return f"### @file:{path_str}" + (
            f":{line_range[0]}-{line_range[1]}" if line_range else ""
        ) + f"\n```\n{text}\n```"
    except FileNotFoundError:
        return f"[file not found: {path_str}]"
    except PermissionError:
        return f"[permission denied: {path_str}]"


def _read_folder(path_str: str) -> str:
    """Read all non-binary files in a directory tree (shallow-first, alphabetical)."""
    p = Path(path_str)
    if not p.is_dir():
        return f"[not a directory: {path_str}]"
    parts = [f"### @folder:{path_str}"]
    for child in sorted(p.rglob("*")):
        if child.is_file():
            try:
                raw = child.read_bytes()
                if _is_binary(raw):
                    parts.append(f"# {child} [binary, skipped]")
                    continue
                text = raw.decode("utf-8", errors="replace")
                parts.append(f"# {child}\n```\n{text}\n```")
            except (PermissionError, OSError):
                parts.append(f"# {child} [unreadable]")
    return "\n".join(parts)


def _run_git(args: list[str]) -> str:
    """Run a git command and return its stdout, or an error string."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"[git error: {result.stderr.strip()}]"
        return result.stdout
    except FileNotFoundError:
        return "[git not found]"
    except subprocess.TimeoutExpired:
        return "[git timed out]"


def _fetch_url(url: str) -> str:
    """Fetch a URL and return plain-text content (strips HTML tags naively)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dolOS/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(512 * 1024)  # max 512 KB
            content = raw.decode("utf-8", errors="replace")
        # Very naive HTML stripping: remove tags
        content = re.sub(r"<[^>]+>", "", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return f"### @url:{url}\n{content.strip()}"
    except urllib.error.URLError as e:
        return f"[url fetch failed: {e}]"
    except Exception as e:
        return f"[url fetch error: {e}]"


def _parse_file_arg(arg: str) -> tuple[str, Optional[tuple[int, int]]]:
    """Parse 'path.py' or 'path.py:10-25' into (path, line_range | None)."""
    if not arg:
        return ("", None)
    # Check for trailing :N-M
    m = re.search(r":(\d+)-(\d+)$", arg)
    if m:
        path = arg[: m.start()]
        return (path, (int(m.group(1)), int(m.group(2))))
    return (arg, None)


def expand_refs(prompt: str, context_window: int = 128_000) -> str:
    """Replace @ref tokens in *prompt* with inline content.

    Pure expansion — mutates nothing in the agent or channel state.
    Returns the expanded prompt string with any limit/warning annotations.
    """
    hard_limit = int(context_window * HARD_LIMIT_RATIO)
    soft_limit = int(context_window * SOFT_LIMIT_RATIO)
    # chars ≈ tokens * 4; we track injected chars
    injected_chars = 0
    over_soft = False

    def _replace(m: re.Match) -> str:
        nonlocal injected_chars, over_soft

        ref_type = m.group(1)
        arg = m.group(2) or ""

        # Hard limit: refuse expansion
        if injected_chars >= hard_limit:
            return f"[{m.group(0).strip()} — context hard limit reached, expansion skipped]"

        # Sensitive path check
        if ref_type in ("file", "folder") and _is_sensitive(arg):
            return f"[{m.group(0).strip()} — blocked: sensitive path]"

        # Expand
        if ref_type == "file":
            path, line_range = _parse_file_arg(arg)
            content = _read_file(path, line_range)
        elif ref_type == "folder":
            content = _read_folder(arg)
        elif ref_type == "diff":
            content = "### @diff\n" + _run_git(["diff"])
        elif ref_type == "staged":
            content = "### @staged\n" + _run_git(["diff", "--staged"])
        elif ref_type == "git":
            try:
                n = int(arg) if arg else 5
            except ValueError:
                n = 5
            content = f"### @git:{n}\n" + _run_git(["log", f"-{n}", "-p"])
        elif ref_type == "url":
            content = _fetch_url(arg)
        else:
            return m.group(0)  # unknown — leave unchanged

        injected_chars += len(content)

        # Soft limit warning (emitted once)
        if injected_chars >= soft_limit and not over_soft:
            over_soft = True
            content = (
                "[WARNING: injected context is large (>25% of context window). "
                "Consider narrowing your @refs.]\n" + content
            )

        return content

    return REF_PATTERN.sub(_replace, prompt)
