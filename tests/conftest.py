"""Pytest test-environment normalization for the sandboxed workspace."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_WORKSPACE_TMP = Path(__file__).resolve().parents[1] / ".tmp-tests" / "workspace-temp"
_USE_WORKSPACE_TMP = os.name == "nt"

if _USE_WORKSPACE_TMP:
    _WORKSPACE_TMP.mkdir(parents=True, exist_ok=True)
    os.environ["TMP"] = str(_WORKSPACE_TMP)
    os.environ["TEMP"] = str(_WORKSPACE_TMP)
    os.environ["TMPDIR"] = str(_WORKSPACE_TMP)
    tempfile.tempdir = str(_WORKSPACE_TMP)


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not _USE_WORKSPACE_TMP:
        return tmp_path_factory.mktemp("pytest-")

    temp_dir = _WORKSPACE_TMP / f"pytest-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir
