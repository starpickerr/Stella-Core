"""G5: frozen backend can open a restricted plugin page and Bridge-invoke."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APP_RESOURCES = (
    REPO / "desktop" / "release" / "mac-arm64" / "Stella.app" / "Contents" / "Resources"
)
DEV_RESOURCES = REPO / "desktop" / "resources"
BACKEND_CANDIDATES = [
    REPO / "desktop" / "build" / "dist" / "stella-backend" / "stella-backend",
    APP_RESOURCES / "backend" / "stella-backend" / "stella-backend",
]


def _resolve_layout() -> tuple[Path, Path, Path] | None:
    backend = next((path for path in BACKEND_CANDIDATES if path.is_file()), None)
    if backend is None:
        return None
    for resources in (DEV_RESOURCES, APP_RESOURCES):
        catalog = resources / "plugin-catalog.json"
        secret = resources / "plugin-signing.secret"
        if catalog.is_file() and secret.is_file():
            return backend, catalog, secret
    return None


@pytest.fixture(scope="module")
def frozen_call(tmp_path_factory):
    layout = _resolve_layout()
    if layout is None:
        pytest.skip("frozen backend + signed catalog/secret not available")
    backend, catalog, secret = layout
    home = tmp_path_factory.mktemp("g5-page-home")
    data = tmp_path_factory.mktemp("g5-page-data")
    port = 19878
    token = "g5-page-smoke"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "STELLA_DATA_DIR": str(data),
            "STELLA_DESKTOP": "1",
            "STELLA_BACKEND_PORT": str(port),
            "STELLA_DESKTOP_INTERNAL_TOKEN": token,
            "STELLA_PLUGIN_CATALOG": str(catalog.resolve()),
            "STELLA_PLUGIN_SIGNING_SECRET": secret.read_text(encoding="utf-8").strip(),
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
        pytest.fail(f"bootstrap/API failed:\n{log.read_text(errors='replace')[-2000:]}")

    def call(method: str, path: str, body: dict | None = None) -> dict | str:
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype or raw.lstrip().startswith("{"):
                return json.loads(raw)
            return raw

    try:
        yield call
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_frozen_bills_page_open_content_and_bridge(frozen_call):
    opened = frozen_call("POST", "/api/plugins/pages/open", {
        "pluginId": "stella.bills",
        "pageId": "bills.main",
        "generation": 1,
    })
    assert opened["status"] == "ok"
    result = opened["result"]
    assert result["channelNonce"]
    content_url = result["contentUrl"]
    assert "bills.main" in content_url
    # contentUrl is typically relative; hit pages/content endpoint shape.
    html = frozen_call(
        "GET",
        f"/api/plugins/pages/content/stella.bills/bills.main?nonce={result['channelNonce']}",
    )
    assert isinstance(html, str)
    assert "stella.bills" in html or "记一笔" in html
    created = frozen_call("POST", "/api/plugins/bridge/invoke", {
        "channelNonce": result["channelNonce"],
        "pluginId": "stella.bills",
        "pageId": "bills.main",
        "generation": 1,
        "method": "create_ledger",
        "input": {
            "name": "冒烟",
            "category": "消费",
            "entry_type": "expense",
            "amount_minor": 900,
            "occurred_at": "2026-10-20T12:00:00+08:00",
        },
    })
    assert created["status"] == "ok"
    assert created["value"]["amount_minor"] == 900
