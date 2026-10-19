"""R03 runtime evidence: real Electron BrowserWindow built by openPluginFrame().

Compiles ``desktop/src/main/plugin-frame.ts`` with the repo's TypeScript, opens it
under the Electron binary (``desktop/node_modules/electron`` or
``STELLA_ELECTRON_BIN``) against a loopback page, and asserts from *inside* the
page that Node globals are absent, inline script/eval/foreign fetch are blocked
and the strict CSP header reaches the page. SKIPs when Electron/tsc/node are
missing. In headless Linux CI run it under ``xvfb-run``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DESKTOP = REPO / "desktop"
HARNESS = REPO / "tests" / "electron" / "plugin_frame_harness.cjs"


def _electron_bin() -> Path | None:
    env = os.environ.get("STELLA_ELECTRON_BIN")
    if env:
        return Path(env) if Path(env).is_file() else None
    dist = DESKTOP / "node_modules" / "electron" / "dist"
    path_txt = DESKTOP / "node_modules" / "electron" / "path.txt"
    if not path_txt.is_file():
        return None
    binary = dist / path_txt.read_text().strip()
    return binary if binary.is_file() else None


@pytest.fixture(scope="module")
def frame_result(tmp_path_factory) -> dict:
    electron = _electron_bin()
    if electron is None:
        pytest.skip("Electron binary not found (npm ci in desktop/ or set STELLA_ELECTRON_BIN)")
    node = shutil.which("node")
    tsc = DESKTOP / "node_modules" / "typescript" / "bin" / "tsc"
    if node is None or not tsc.is_file():
        pytest.skip("node or desktop TypeScript not installed")
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY; run under xvfb-run")

    work = tmp_path_factory.mktemp("frame")
    out = work / "js"
    compiled = subprocess.run(
        [
            node, str(tsc), str(DESKTOP / "src" / "main" / "plugin-frame.ts"),
            "--outDir", str(out), "--module", "commonjs", "--target", "ES2020",
            "--strict", "--skipLibCheck", "--esModuleInterop", "--typeRoots",
            str(DESKTOP / "node_modules" / "@types"),
        ],
        cwd=str(DESKTOP), capture_output=True, text=True, timeout=180,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    frame_js = out / "plugin-frame.js"
    assert frame_js.is_file()

    env = os.environ.copy()
    env.update(
        HOME=str(work / "home"),
        STELLA_DATA_DIR=str(work / "data"),
        STELLA_FRAME_JS=str(frame_js),
        STELLA_FRAME_USER_DATA=str(work / "userdata"),
        NODE_PATH=str(DESKTOP / "node_modules"),
    )
    env.pop("ELECTRON_RUN_AS_NODE", None)
    (work / "home").mkdir()
    args = [str(electron), str(HARNESS)]
    if sys.platform.startswith("linux"):
        args.insert(1, "--no-sandbox")  # CI containers lack the SUID sandbox helper
    try:
        proc = subprocess.run(
            args, env=env, cwd=str(work), capture_output=True, text=True, timeout=90
        )
    except subprocess.TimeoutExpired:
        pytest.fail("electron harness timed out")
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("G5_RESULT ")]
    assert lines, f"rc={proc.returncode}\nstdout={proc.stdout[-1500:]}\nstderr={proc.stderr[-1500:]}"
    result = json.loads(lines[-1][len("G5_RESULT "):])
    assert "error" not in result, result["error"]
    assert not (work / "data").exists()
    return result


def test_frame_webpreferences_hardened(frame_result):
    prefs = frame_result["prefs"]
    assert prefs["sandbox"] is True
    assert prefs["nodeIntegration"] is False
    assert prefs["contextIsolation"] is True
    assert prefs["webSecurity"] is True
    assert prefs["preload"] is None


def test_frame_page_has_no_node_globals(frame_result):
    probe = frame_result["probe"]
    assert probe["requireType"] == "undefined"
    assert probe["processType"] == "undefined"
    assert probe["moduleType"] == "undefined"
    assert probe["BufferType"] == "undefined"


def test_frame_csp_header_delivered_and_enforced(frame_result):
    probe = frame_result["probe"]
    assert probe["cspHeader"] == _expected_csp()
    assert probe["inlineScriptRan"] is False
    assert probe["evalAllowed"] is False
    assert probe["foreignFetch"] == "blocked"
    assert any(v.startswith("script-src") for v in frame_result["violations"])


def test_frame_identity_is_host_bound(frame_result):
    ident = frame_result["identity"]
    assert ident["pluginId"] == "g5.harness"
    assert ident["generation"] == 0


def test_frame_blocks_foreign_navigation_and_window_open(frame_result):
    nav = frame_result["navigation"]
    assert nav["navigatedAway"] is False
    assert "127.0.0.1" in nav["urlAfterForeignAssign"]
    assert "example.invalid" not in nav["urlAfterForeignAssign"]
    assert nav["windowOpen"] == "denied"


def _expected_csp() -> str:
    text = (DESKTOP / "src" / "main" / "plugin-frame.ts").read_text(encoding="utf-8")
    start = text.index("PLUGIN_FRAME_CSP = [")
    block = text[start : text.index("].join", start)]
    parts = [ln.strip().rstrip(",").strip('"') for ln in block.splitlines()[1:] if ln.strip()]
    return "; ".join(parts)
