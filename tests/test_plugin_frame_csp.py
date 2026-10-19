"""R03 structural checks for plugin-frame hardening (CSP / sandbox / no Node)."""

from __future__ import annotations

from pathlib import Path

FRAME = Path(__file__).resolve().parents[1] / "desktop" / "src" / "main" / "plugin-frame.ts"


def test_plugin_frame_exports_strict_csp():
    text = FRAME.read_text(encoding="utf-8")
    assert "PLUGIN_FRAME_CSP" in text
    assert "default-src 'self'" in text
    assert "script-src 'self'" in text
    assert "object-src 'none'" in text
    assert "frame-src 'none'" in text


def test_plugin_frame_disables_node_and_privileged_preload():
    text = FRAME.read_text(encoding="utf-8")
    assert "nodeIntegration: false" in text
    assert "sandbox: true" in text
    assert "contextIsolation: true" in text
    assert "preload: undefined" in text
    assert "setWindowOpenHandler" in text
    assert "will-navigate" in text
    assert "Content-Security-Policy" in text


def test_package_json_ships_plugin_runner_resource():
    pkg = Path(__file__).resolve().parents[1] / "desktop" / "package.json"
    text = pkg.read_text(encoding="utf-8")
    assert "stella-plugin-runner" in text
    assert "backend/stella-plugin-runner" in text


def test_build_backend_builds_runner():
    script = Path(__file__).resolve().parents[1] / "desktop" / "build" / "build-backend.sh"
    text = script.read_text(encoding="utf-8")
    assert "stella-plugin-runner.spec" in text
