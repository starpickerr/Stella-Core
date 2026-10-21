"""G5: packaged plugin-catalog ships signed ZIPs (no plugin-seed trees)."""

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
PACKAGES = RESOURCES / "plugin-packages"
SECRET = RESOURCES / "plugin-signing.secret"


@pytest.mark.skipif(not BACKEND.is_file(), reason="Stella.app not built")
@pytest.mark.skipif(not CATALOG.is_file(), reason="plugin-catalog.json not present in Stella.app")
def test_packaged_catalog_lists_domains_with_signed_package_urls():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    ids = {row["pluginId"] for row in data["plugins"]}
    assert ids == {
        "stella.bills",
        "stella.calendar",
        "stella.tasks",
        "stella.knowledge",
        "stella.memory",
        "stella.briefing",
        "stella.automation",
        "stella.agent-hub",
    }
    for row in data["plugins"]:
        assert not str(row.get("path") or "").startswith("plugin-seed/")
        assert row.get("url", "").startswith("plugin-packages/")
        assert row.get("sha256")
        assert row.get("version")
        assert (RESOURCES / row["url"]).is_file()
    assert not SEED.exists(), "Core-only DMG must not ship plugin-seed"
    assert PACKAGES.is_dir()
    assert SECRET.is_file()


@pytest.mark.skipif(not BACKEND.is_file(), reason="Stella.app not built")
@pytest.mark.skipif(not CATALOG.is_file(), reason="plugin-catalog.json not present in Stella.app")
@pytest.mark.skipif(not SECRET.is_file(), reason="plugin-signing.secret not present in Stella.app")
def test_frozen_backend_bootstraps_from_signed_package_urls(tmp_path):
    """Frozen exe discovers Resources catalog and installs from signed ZIPs."""
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "STELLA_DESKTOP": "1",
            "STELLA_BACKEND_PORT": "18793",
            "STELLA_DESKTOP_INTERNAL_TOKEN": "seed",
            "STELLA_PLUGIN_SIGNING_SECRET": SECRET.read_text(encoding="utf-8").strip(),
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
    deadline = time.time() + 90
    text = ""
    while time.time() < deadline:
        text = log.read_text(errors="replace") if log.is_file() else ""
        if "Plugin bootstrap status=ok" in text:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    assert "Plugin bootstrap status=ok" in text, text[-2000:]
    currents = list((home / "stella" / "plugin-packages" / "packages").glob("stella.*/current.json"))
    assert len(currents) == 8
