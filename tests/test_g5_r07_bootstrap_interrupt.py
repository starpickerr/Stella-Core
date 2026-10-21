"""R07 slice: killing first-boot bootstrap then restarting keeps one current pointer per domain."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO.parent / "Stella-Plugins" / "catalog" / "official.json"
BACKEND = (
    REPO
    / "desktop"
    / "release"
    / "mac-arm64"
    / "Stella.app"
    / "Contents"
    / "Resources"
    / "backend"
    / "stella-backend"
    / "stella-backend"
)
DOMAINS = (
    "stella.bills",
    "stella.calendar",
    "stella.tasks",
    "stella.knowledge",
    "stella.memory",
    "stella.briefing",
    "stella.automation",
    "stella.agent-hub",
)


@pytest.mark.skipif(not BACKEND.is_file(), reason="frozen Stella.app backend missing")
@pytest.mark.skipif(not CATALOG.is_file(), reason="Stella-Plugins catalog missing")
def test_bootstrap_survives_kill_with_single_current_pointers(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "STELLA_DESKTOP": "1",
            "STELLA_BACKEND_PORT": "18792",
            "STELLA_DESKTOP_INTERNAL_TOKEN": "r07",
            "STELLA_PLUGIN_CATALOG": str(CATALOG.resolve()),
            "PATH": "/nonexistent",
        }
    )
    env.pop("PYTHONPATH", None)
    log1 = home / "boot1.log"
    proc = subprocess.Popen(
        [str(BACKEND)],
        env=env,
        stdout=log1.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(REPO),
    )
    time.sleep(0.35)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)

    log2 = home / "boot2.log"
    proc2 = subprocess.Popen(
        [str(BACKEND)],
        env=env,
        stdout=log2.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(REPO),
    )
    deadline = time.time() + 45
    ok = False
    while time.time() < deadline:
        text = log2.read_text(errors="replace") if log2.is_file() else ""
        if "Plugin bootstrap status=ok" in text:
            ok = True
            break
        if proc2.poll() is not None:
            break
        time.sleep(0.2)
    proc2.send_signal(signal.SIGTERM)
    try:
        proc2.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc2.kill()
    assert ok, log2.read_text(errors="replace")[-2000:]

    packages = home / "stella" / "plugin-packages" / "packages"
    currents = {p.parent.name for p in packages.glob("stella.*/current.json")}
    assert currents == set(DOMAINS)
    digest_dirs = list(packages.glob("stella.*/*/*"))
    assert len(digest_dirs) <= 16
