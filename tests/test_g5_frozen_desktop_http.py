"""G5: after first-boot install, frozen-backend desktop HTTP writes via plugins.

Uses the onedir backend from ``desktop/build/dist`` or ``desktop/release/.../Stella.app``
when present. Requires sibling ``Stella-Plugins/catalog/official.json``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO.parent / "Stella-Plugins" / "catalog" / "official.json"
CANDIDATES = [
    # Prefer the freshly built onedir so grant/bootstrap fixes are exercised
    # without requiring a full DMG rebuild on every iteration.
    REPO / "desktop" / "build" / "dist" / "stella-backend" / "stella-backend",
    REPO
    / "desktop"
    / "release"
    / "mac-arm64"
    / "Stella.app"
    / "Contents"
    / "Resources"
    / "backend"
    / "stella-backend"
    / "stella-backend",
]


def _backend() -> Path | None:
    for path in CANDIDATES:
        if path.is_file():
            return path
    return None


@pytest.fixture(scope="module")
def frozen_backend_http(tmp_path_factory):
    backend = _backend()
    if backend is None:
        pytest.skip("frozen stella-backend not built")
    if not CATALOG.is_file():
        pytest.skip("Stella-Plugins catalog missing")
    home = tmp_path_factory.mktemp("g5-http-home")
    data = tmp_path_factory.mktemp("g5-http-data")
    port = 19877
    token = "g5-frozen-http-token"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "STELLA_DATA_DIR": str(data),
            "STELLA_DESKTOP": "1",
            "STELLA_BACKEND_PORT": str(port),
            "STELLA_DESKTOP_INTERNAL_TOKEN": token,
            "STELLA_PLUGIN_CATALOG": str(CATALOG.resolve()),
            "PATH": "/nonexistent",
        }
    )
    env.pop("PYTHONPATH", None)
    log = home / "backend.log"
    proc = subprocess.Popen(
        [str(backend)],
        env=env,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        cwd=str(REPO),
    )
    deadline = time.time() + 90
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
        pytest.fail(f"bootstrap/API did not succeed:\n{log.read_text(errors='replace')[-2000:]}")
    time.sleep(0.3)

    def call(method: str, path: str, body: dict | None = None) -> dict:
        data_bytes = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data_bytes,
            method=method,
            headers={
                "X-Stella-Desktop-Token": token,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        yield call
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_frozen_desktop_bills_create_and_list(frozen_backend_http):
    created = frozen_backend_http(
        "POST",
        "/api/bills/ledger",
        {
            "name": "午餐",
            "category": "消费",
            "entry_type": "expense",
            "amount_minor": 3200,
            "occurred_at": "2026-08-02T12:30:00+08:00",
        },
    )
    assert created["status"] == "success"
    assert created["entry"]["amount_minor"] == 3200
    listed = frozen_backend_http("GET", "/api/bills/ledger?year=2026&month=8")
    assert listed["status"] == "success"
    assert any(row["id"] == created["entry"]["id"] for row in listed["entries"])


def test_frozen_desktop_todos_create(frozen_backend_http):
    created = frozen_backend_http("POST", "/api/todos", {"title": "买菜", "status": "todo"})
    assert created["status"] == "success"
    assert created["todo"]["title"] == "买菜"
