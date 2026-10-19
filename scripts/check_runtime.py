"""Resolve local quality tooling on supported desktop platforms."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _conda_stella_python(platform: str | None = None) -> Path | None:
    """Prefer the local conda env named Stella for development."""
    nt = (platform or os.name) == "nt"
    exe = "python.exe" if nt else "bin/python"

    override = (os.environ.get("STELLA_PYTHON") or "").strip()
    if override:
        path = Path(override)
        return path if path.is_file() else None

    conda_prefix = (os.environ.get("CONDA_PREFIX") or "").strip()
    if conda_prefix and Path(conda_prefix).name == "Stella":
        candidate = Path(conda_prefix) / exe
        if candidate.is_file():
            return candidate

    home = Path.home()
    roots = (
        Path("/opt/anaconda3"),
        Path("/usr/local/anaconda3"),
        home / "anaconda3",
        home / "miniconda3",
        home / "mambaforge",
        home / "miniforge3",
        home / ".conda",
    )
    for root in roots:
        candidate = root / "envs" / "Stella" / exe
        if candidate.is_file():
            return candidate
    return None


def python_path(root, platform=None):
    """Resolve the Stella development interpreter.

    Order: ``STELLA_PYTHON`` → active/local conda env ``Stella`` → project
    ``.venv`` (kept for CI). Local development should use conda Stella only.
    """
    nt = (platform or os.name) == "nt"
    conda_python = _conda_stella_python(platform)
    if conda_python is not None:
        return conda_python
    return Path(root) / (".venv/Scripts/python.exe" if nt else ".venv/bin/python")


def npm_path():
    return shutil.which("npm") or ("npm.cmd" if os.name == "nt" else "npm")
