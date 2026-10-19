"""G5: fresh DMG attach → copy app → first-boot installs signed catalog with scoped grants.

Mirrors the Finder path without GUI: ``hdiutil attach`` the release DMG, copy
``Stella.app`` to a temp Applications-like folder, then run the packaged
backend against a temp HOME and assert bootstrap + write authorization.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DMG = REPO / "desktop" / "release" / "Stella-0.0.5-arm64.dmg"


def _hdiutil(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["hdiutil", *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def installed_app(tmp_path_factory):
    if not DMG.is_file():
        pytest.skip(f"DMG not built: {DMG}")
    work = tmp_path_factory.mktemp("dmg-install")
    mount = work / "mount"
    mount.mkdir()
    apps = work / "Applications"
    apps.mkdir()
    attach = _hdiutil("attach", str(DMG), "-nobrowse", "-readonly", "-mountpoint", str(mount))
    assert attach.returncode == 0
    try:
        src = mount / "Stella.app"
        assert src.is_dir(), f"Stella.app missing on DMG volume: {list(mount.iterdir())}"
        dest = apps / "Stella.app"
        subprocess.run(["ditto", str(src), str(dest)], check=True)
        resources = dest / "Contents" / "Resources"
        backend = resources / "backend" / "stella-backend" / "stella-backend"
        catalog = resources / "plugin-catalog.json"
        secret = resources / "plugin-signing.secret"
        assert backend.is_file()
        assert catalog.is_file()
        assert secret.is_file()
        assert not (resources / "plugin-seed").exists()
        yield {
            "app": dest,
            "backend": backend,
            "catalog": catalog,
            "secret": secret.read_text(encoding="utf-8").strip(),
            "resources": resources,
        }
    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount), "-force"],
            check=False,
            capture_output=True,
            text=True,
        )


@pytest.fixture(scope="module")
def dmg_first_boot(installed_app, tmp_path_factory):
    home = tmp_path_factory.mktemp("dmg-home")
    data = tmp_path_factory.mktemp("dmg-data")
    port = 19881
    token = "g5-dmg-smoke"
    log = home / "backend.log"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "STELLA_DATA_DIR": str(data),
            "STELLA_DESKTOP": "1",
            "STELLA_BACKEND_PORT": str(port),
            "STELLA_DESKTOP_INTERNAL_TOKEN": token,
            "STELLA_PLUGIN_SIGNING_SECRET": installed_app["secret"],
            "PATH": "/nonexistent",
        }
    )
    env.pop("STELLA_PLUGIN_CATALOG", None)
    env.pop("PYTHONPATH", None)
    proc = subprocess.Popen(
        [str(installed_app["backend"])],
        env=env,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(REPO),
    )
    deadline = time.time() + 120
    ready = False
    while time.time() < deadline:
        text = log.read_text(errors="replace") if log.is_file() else ""
        if "Local desktop API ready" in text and "Plugin bootstrap status=ok" in text:
            ready = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    if not ready:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        pytest.fail(f"DMG first-boot failed:\n{log.read_text(errors='replace')[-2500:]}")

    def call(method: str, path: str, body: dict | None = None) -> dict:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=payload,
            method=method,
            headers={
                "X-Stella-Desktop-Token": token,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        yield {
            "call": call,
            "home": home,
            "data": data,
            "log": log,
            "app": installed_app,
        }
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_dmg_copy_has_core_only_signed_catalog(installed_app):
    catalog = json.loads(installed_app["catalog"].read_text(encoding="utf-8"))
    assert len(catalog["plugins"]) == 7
    for row in catalog["plugins"]:
        assert row["url"].startswith("plugin-packages/")
        assert (installed_app["resources"] / row["url"]).is_file()


def test_dmg_first_boot_issues_scoped_grants_and_writes(dmg_first_boot):
    home = dmg_first_boot["home"]
    auth = home / "stella" / "plugin-packages" / "management" / "authorization.sqlite"
    # STELLA_DATA_DIR may own the workspace instead of HOME/stella.
    if not auth.is_file():
        data = dmg_first_boot["data"]
        candidates = list(data.rglob("authorization.sqlite")) + list(home.rglob("authorization.sqlite"))
        assert candidates, f"no authorization.sqlite under {home} or {data}"
        auth = candidates[0]
    con = sqlite3.connect(auth)
    rows = con.execute("select ref, value from grants").fetchall()
    assert len(rows) >= 14  # at least interactive+background × required caps across domains
    write_grants = [ref for ref, _ in rows if "bills.write" in ref]
    assert write_grants, rows[:5]
    created = dmg_first_boot["call"](
        "POST",
        "/api/bills/ledger",
        {
            "name": "DMG冒烟",
            "category": "消费",
            "entry_type": "expense",
            "amount_minor": 1200,
            "occurred_at": "2026-10-20T02:00:00+08:00",
        },
    )
    assert created["status"] == "success"
    assert created["entry"]["amount_minor"] == 1200
