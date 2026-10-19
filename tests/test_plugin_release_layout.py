"""R01 packaging layout: frozen backend discovers sibling stella-plugin-runner.

Simulates the Electron extraResources layout::

    <resources>/backend/stella-backend/stella-backend
    <resources>/backend/stella-plugin-runner/stella-plugin-runner

without requiring a full electron-builder DMG when a prebuilt runner exists.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.plugins.host import PluginSession, resolve_runner_command
from core.plugins.registry import PluginRegistry

REPO = Path(__file__).resolve().parent.parent
RUNNER_SPEC = REPO / "desktop" / "build" / "stella-plugin-runner.spec"


def _pyinstaller() -> str | None:
    env = os.environ.get("STELLA_PYINSTALLER_PATH")
    if env and Path(env).is_file():
        return env
    which = shutil.which("pyinstaller")
    return which


@pytest.fixture(scope="module")
def frozen_runner(tmp_path_factory) -> Path:
    pyi = _pyinstaller()
    if not pyi:
        pytest.skip("PyInstaller not available")
    work = tmp_path_factory.mktemp("runner-build")
    dist = work / "dist"
    proc = subprocess.run(
        [
            pyi,
            str(RUNNER_SPEC),
            "--noconfirm",
            "--distpath",
            str(dist),
            "--workpath",
            str(work / "work"),
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    binary = dist / "stella-plugin-runner" / "stella-plugin-runner"
    if sys.platform == "win32":
        binary = dist / "stella-plugin-runner" / "stella-plugin-runner.exe"
    assert binary.is_file(), f"missing frozen runner at {binary}"
    return binary


def test_release_layout_resolve_runner_from_backend_tree(frozen_runner, tmp_path):
    """Mirror Electron Resources/backend/{stella-backend,stella-plugin-runner}."""
    resources = tmp_path / "Resources"
    backend = resources / "backend" / "stella-backend"
    runner_dir = resources / "backend" / "stella-plugin-runner"
    backend.mkdir(parents=True)
    runner_dir.mkdir(parents=True)
    # Fake frozen backend executable next to real runner binary.
    fake_backend = backend / ("stella-backend.exe" if sys.platform == "win32" else "stella-backend")
    fake_backend.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_backend.chmod(0o755)
    dest = runner_dir / frozen_runner.name
    # Copy whole onedir so dylibs resolve.
    shutil.copytree(frozen_runner.parent, runner_dir, dirs_exist_ok=True)
    cmd = resolve_runner_command(
        frozen=True,
        executable=str(fake_backend),
        environ={},
    )
    assert cmd == [str(dest.resolve())] or cmd == [str((runner_dir / frozen_runner.name).resolve())]
    assert Path(cmd[0]).is_file()
    assert "stella-plugin-runner" in cmd[0]


def test_release_layout_session_starts_alpha_without_dev_module(frozen_runner, tmp_path, monkeypatch):
    resources = tmp_path / "Resources"
    backend = resources / "backend" / "stella-backend"
    runner_dir = resources / "backend" / "stella-plugin-runner"
    backend.mkdir(parents=True)
    shutil.copytree(frozen_runner.parent, runner_dir, dirs_exist_ok=True)
    fake_backend = backend / "stella-backend"
    fake_backend.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_backend.chmod(0o755)

    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("STELLA_DATA_DIR", str(data))
    monkeypatch.delenv("STELLA_PLUGIN_RUNNER", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PYTHONPATH", raising=False)

    # Force frozen discovery relative to fake backend path via STELLA_PLUGIN_RUNNER
    # only if resolve fails — prefer resolve_runner_command path.
    runner = resolve_runner_command(frozen=True, executable=str(fake_backend), environ={})
    monkeypatch.setenv("STELLA_PLUGIN_RUNNER", runner[0])

    registry = PluginRegistry()
    session = PluginSession(
        REPO / "samples" / "plugins" / "alpha",
        source_label="sample",
        registry=registry,
        runner_command=runner,
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.sample.alpha"
        assert session._proc is not None
        assert "-m" not in session._proc.args
        assert "core.plugins.runner" not in " ".join(session._proc.args)
    finally:
        session.dispose()
    # No app business init side effects in data dir.
    assert not any(data.rglob("*")) if data.exists() else True
