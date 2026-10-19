"""Frozen/dedicated runner must not boot app.py business stack."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry


def test_runner_cli_refuses_if_app_imported():
    code = (
        "import app\n"
        "from core.plugins.runner.cli import main\n"
        "raise SystemExit(main())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "refuses polluted process" in (proc.stderr + proc.stdout)


def test_dedicated_runner_command_starts_sample():
    registry = PluginRegistry()
    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="sample",
        registry=registry,
        runner_command=[sys.executable, "-m", "core.plugins.runner.cli"],
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.sample.alpha"
    finally:
        session.dispose()
