"""Pre-execution bash command validator.

Checks commands against a list of dangerous patterns before they reach the
subprocess sandbox. If a command matches, the executor returns an error dict
without executing — the sandbox never runs.

This is a defence-in-depth layer on top of SandboxPolicy (which restricts
what code can do at runtime). The validator prevents clearly dangerous
commands from being attempted at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# Each tuple is (regex_pattern, human_readable_reason).
# Patterns use re.IGNORECASE.
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # Recursive deletes from root or home
    (r"\brm\s+(-\w*[rf]\w*\s+){0,3}/", "destructive recursive delete from root"),
    (r"\brm\s+(-\w*[rf]\w*\s+){0,3}~", "destructive recursive delete from home"),
    # Raw device writes
    (r"\bdd\b.*\bof=/dev/", "raw device write"),
    # Overwrite critical system files
    (r">\s*/etc/", "overwrite system file"),
    (r">\s*/boot/", "overwrite boot file"),
    # Dangerous permission changes
    (r"\bchmod\s+(777|a\+w)\s+/", "world-writable root path"),
    # Pipe to shell — remote code execution
    (r"\|\s*(sudo\s+)?(sh|bash|zsh|fish|dash)\b", "pipe to shell interpreter"),
    (r"\bcurl\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)", "remote code execution via curl-pipe"),
    (r"\bwget\b[^|]*\|\s*(sudo\s+)?(sh|bash|zsh)", "remote code execution via wget-pipe"),
    # Command substitution in the command string (indicates injection risk)
    (r"\$\([^)]*\)", "command substitution"),
    (r"`[^`]+`", "backtick command substitution"),
    # IFS / environment manipulation tricks
    (r"\bIFS\s*=", "IFS manipulation"),
    # Fork bombs
    (r":\s*\(\s*\)\s*\{", "fork bomb pattern"),
    # Hex/base64 encoded payloads piped to shell
    (r"\bbase64\b.*--decode.*\|", "base64-decode pipe (potential hidden payload)"),
    (r"\becho\b.*\|.*base64.*-d.*\|", "base64-decode echo pipe"),
    # Process kill signals targeting critical IDs
    (r"\bkill\s+-9\s+1\b", "kill init process"),
    # Disk wipe
    (r"\bshred\b.*(/dev/[sh]d|/dev/nvme)", "disk shred"),
    # Wildcard deletes of entire directories
    (r"\brm\s+-[rf]+\s+\*", "wildcard recursive delete"),
    # Crontab overwrites
    (r"\bcrontab\b.*-r\b", "remove all crontabs"),
    # Firewall flush
    (r"\biptables\b.*-F\b", "flush all iptables rules"),
    (r"\bnft\b.*flush\b", "flush nftables ruleset"),
    # Python/Perl/Ruby/Node one-liner executing downloaded code
    (r"\bpython[23]?\b.*-c.*__import__.*urllib", "python remote exec one-liner"),
    # Unicode control characters (invisible injection)
    (r"[\u202a-\u202e\u2066-\u2069\u200b-\u200f]", "unicode control/bidi character injection"),
]

_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in DANGEROUS_PATTERNS
]


@dataclass
class ValidationResult:
    is_safe: bool
    reason: str = ""
    matched_pattern: str = field(default="", repr=False)


def validate_bash_command(command: str) -> ValidationResult:
    """Check a bash command string against all dangerous patterns.

    Args:
        command: The shell command string to validate.

    Returns:
        ValidationResult with is_safe=True if the command is allowed,
        or is_safe=False with a reason if it matches a dangerous pattern.
    """
    for compiled, reason in _COMPILED:
        m = compiled.search(command)
        if m:
            return ValidationResult(
                is_safe=False,
                reason=reason,
                matched_pattern=compiled.pattern,
            )
    return ValidationResult(is_safe=True)
