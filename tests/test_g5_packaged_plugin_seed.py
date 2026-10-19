"""G5: packaged plugin-catalog + seed trees install without sibling checkout."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "desktop" / "release" / "mac-arm64" / "Stella.app"
RESOURCES = APP / "Contents" / "Resources"
BACKEND = RESOURCES / "backend" / "stella-backend" / "stella-backend"
CATALOG = RESOURCES / "plugin-catalog.json"
SEED = RESOURCES / "plugin-seed"


@pytest.mark.skipif(not BACKEND.is_file(), reason="Stella.app not built")
@pytest.mark.skipif(not CATALOG.is_file(), reason="plugin-catalog.json not seeded into Stella.app")
@pytest.mark.skipif(not SEED.is_dir(), reason="plugin-seed not present in Stella.app")
def test_packaged_catalog_lists_seven_seeded_domains():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    ids = {row["pluginId"] for row in data["plugins"]}
    assert ids == {
        "stella.bills",
        "stella.calendar",
        "stella.tasks",
        "stella.email",
        "stella.elearning",
        "stella.briefing",
        "stella.automation",
    }
    for row in data["plugins"]:
        assert row["path"].startswith("plugin-seed/")
        assert (RESOURCES / row["path"]).is_dir()


@pytest.mark.skipif(not BACKEND.is_file(), reason="Stella.app not built")
@pytest.mark.skipif(not CATALOG.is_file(), reason="plugin-catalog.json not seeded into Stella.app")
def test_frozen_backend_bootstraps_from_packaged_catalog_only(tmp_path, monkeypatch):
    """No STELLA_PLUGIN_CATALOG env — frozen exe discovers Resources/plugin-catalog.json."""
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "STELLA_DESKTOP": "1",
            "STELLA_BACKEND_PORT": "18793",
            "STELLA_DESKTOP_INTERNAL_TOKEN": "seed",
            "PATH": "/nonexistent",
        }
    )
    env.pop("STELLA_PLUGIN_CATALOG", None)
    env.pop("PYTHONPATH", None)

    log = home / "boot.log"
    proc = subprocess.Popen(
        [str(BACKEND)],
        env=env,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(REPO),
    )
    deadline = time.time() + 45
    ok = False
    while time.time() < deadline:
        text = log.read_text(errors="replace") if log.is_file() else ""
        if "Plugin bootstrap status=ok" in text:
            ok = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    assert ok, log.read_text(errors="replace")[-2000:]
    currents = list((home / "stella" / "plugin-packages" / "packages").glob("stella.*/current.json"))
    assert len(currents) == 7
