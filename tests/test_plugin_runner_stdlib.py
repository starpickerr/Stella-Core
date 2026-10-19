"""Frozen runner must ship stdlib modules business plugins need (R01 / G5)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNNER_SPEC = REPO / "desktop" / "build" / "stella-plugin-runner.spec"


def _pyinstaller() -> str | None:
    env = os.environ.get("STELLA_PYINSTALLER_PATH")
    if env and Path(env).is_file():
        return env
    return shutil.which("pyinstaller")


@pytest.fixture(scope="module")
def frozen_runner(tmp_path_factory) -> Path:
    pyi = _pyinstaller()
    if not pyi:
        pytest.skip("PyInstaller not available")
    work = tmp_path_factory.mktemp("runner-stdlib-build")
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
    assert binary.is_file()
    return binary


def _write_sqlite_plugin(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "manifestVersion": 1,
                "id": "stella.sample.sqlite",
                "name": "sqlite probe",
                "version": "1.0.0",
                "hostApi": "^1.0.0",
                "runtime": {"kind": "python", "entry": "backend/main.py", "abi": "cp312"},
                "contributes": {"services": ["stella.sample.sqlite@1"]},
                "permissions": [{"capability": "sample.probe", "required": True}],
            }
        ),
        encoding="utf-8",
    )
    backend = root / "backend"
    backend.mkdir()
    (backend / "main.py").write_text(
        "import sqlite3\n"
        "SERVICE_DESCRIPTORS = [{'contract': 'stella.sample.sqlite@1', 'methods': "
        "[{'name': 'probe', 'permissions': ['sample.probe']}]}]\n"
        "\n"
        "def handle(method, params):\n"
        "    if method == 'probe':\n"
        "        return {\n"
        "            'status': 'succeeded',\n"
        "            'sideEffects': 'none',\n"
        "            'value': {'ok': True, 'sqlite': sqlite3.sqlite_version},\n"
        "        }\n"
        "    return {\n"
        "        'status': 'failed',\n"
        "        'sideEffects': 'none',\n"
        "        'error': {'code': 'not_found', 'message': method},\n"
        "    }\n",
        encoding="utf-8",
    )
    return root


def test_sqlite_probe_declares_the_invoked_method(tmp_path):
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry

    session = PluginSession(_write_sqlite_plugin(tmp_path / "probe"),
                            source_label="stdlib-probe", registry=PluginRegistry())
    try:
        session.start()
        assert session.invoke("probe")["value"]["ok"] is True
    finally:
        session.dispose()


def test_frozen_runner_can_import_sqlite3_for_plugin(frozen_runner, tmp_path, monkeypatch):
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry

    plugin = _write_sqlite_plugin(tmp_path / "sqlite-plugin")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    session = PluginSession(
        plugin,
        source_label="stdlib-probe",
        registry=PluginRegistry(),
        runner_command=[str(frozen_runner)],
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.sample.sqlite"
        result = session.invoke("probe", {})
        assert result["status"] == "succeeded"
        assert result["value"]["ok"] is True
        assert result["value"]["sqlite"]
    finally:
        session.dispose()


@pytest.mark.parametrize(
    "domain",
    ["bills", "tasks", "calendar", "email", "elearning", "briefing", "automation"],
)
def test_frozen_runner_initializes_default_domain_plugins(frozen_runner, domain, monkeypatch):
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry

    sibling = REPO.parent / "Stella-Plugins" / "plugins" / domain
    workspace = REPO / "stella-plugins-workspace" / "plugins" / domain
    root = sibling if sibling.is_dir() else workspace
    if not root.is_dir():
        pytest.skip(f"missing plugin package for {domain}")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    session = PluginSession(
        root,
        source_label=f"stdlib-{domain}",
        registry=PluginRegistry(),
        runner_command=[str(frozen_runner)],
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == f"stella.{domain}"
    finally:
        session.dispose()
