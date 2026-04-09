"""Permission layer for dolOS skill execution (Gap 1).

Provides ``PermissionPolicy`` — a declarative filter applied before schemas
are sent to the LLM — and ``filter_schemas()`` which enforces it.

Rules evaluated in order:
1. If ``allow_only`` is set, only names in that set pass.
2. Names in ``deny_names`` are removed.
3. Names matching any prefix in ``deny_prefixes`` are removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PermissionPolicy:
    """Declarative permission filter for LLM-visible tool schemas.

    Attributes:
        deny_names:    Exact skill names to block entirely.
        deny_prefixes: Block any skill whose name starts with one of these.
        allow_only:    If set, *only* skills in this set are allowed (whitelist).
                       ``deny_names`` and ``deny_prefixes`` are still applied on
                       top of the whitelist.
    """

    deny_names: set[str] = field(default_factory=set)
    deny_prefixes: set[str] = field(default_factory=set)
    allow_only: set[str] | None = None


def filter_schemas(
    schemas: list[dict[str, Any]],
    policy: PermissionPolicy,
) -> list[dict[str, Any]]:
    """Return the subset of *schemas* permitted by *policy*.

    Args:
        schemas: List of OpenAI-compatible tool schema dicts (must have ``"name"``).
        policy:  The active ``PermissionPolicy``.

    Returns:
        Filtered list; original dicts are not copied.
    """
    result: list[dict[str, Any]] = []
    for schema in schemas:
        name: str = schema.get("name", "")

        # Rule 1: whitelist — if allow_only is set, name must appear in it
        if policy.allow_only is not None and name not in policy.allow_only:
            continue

        # Rule 2: deny exact name
        if name in policy.deny_names:
            continue

        # Rule 3: deny by prefix
        if any(name.startswith(prefix) for prefix in policy.deny_prefixes):
            continue

        result.append(schema)
    return result
