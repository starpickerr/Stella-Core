"""P1a/P1b: two-source runner sessions, generation, and registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry


@pytest.fixture
def registry():
    return PluginRegistry()


def test_two_sources_same_path(registry):
    alpha = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="first-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    beta = PluginSession(
        Path("samples/plugins/beta"),
        source_label="third-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    try:
        a = alpha.start()
        b = beta.start()
        assert a["initialize"]["abi"] == "cp312"
        assert b["initialize"]["abi"] == "cp312"
        assert registry.owner_of("stella.sample.alpha@1") == "stella.sample.alpha"
        assert registry.owner_of("stella.sample.beta@1") == "stella.sample.beta"
        ping_a = alpha.invoke("ping", {"echo": 1})
        ping_b = beta.invoke("ping", {"echo": 2})
        assert ping_a["value"]["plugin"] == "alpha"
        assert ping_b["value"]["plugin"] == "beta"
    finally:
        alpha.dispose()
        beta.dispose()
    assert registry.get("stella.sample.alpha") is None
    assert registry.get("stella.sample.beta") is None


def test_stale_generation_rejected(registry):
    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="first-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    try:
        session.start()
        snap = registry.get("stella.sample.alpha")
        assert snap is not None
        with pytest.raises(PermissionError):
            registry.require_generation("stella.sample.alpha", snap.generation + 1)
    finally:
        session.dispose()


def test_worker_uses_selected_interpreter_not_implicit_system(registry):
    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="first-party-sample",
        registry=registry,
        python_executable=sys.executable,
    )
    try:
        result = session.start()
        assert result["initialize"]["apiVersion"] == "1.0.0"
    finally:
        session.dispose()


def _runtime_fixture(tmp_path, body):
    import json
    import shutil

    root = tmp_path / "plugin"
    shutil.copytree("samples/plugins/alpha", root)
    manifest = json.loads((root / "plugin.json").read_text())
    (root / manifest["runtime"]["entry"]).write_text(body)
    return root


def test_hung_worker_timeout_revokes_contributions_and_disposes(tmp_path, registry):
    import threading
    import time
    from core.plugins.authz import PluginAuthorizationStore

    root = _runtime_fixture(tmp_path, 'import time\ndef handle(method, params):\n    time.sleep(60)\n')
    authz = PluginAuthorizationStore()
    authz.issue(grant_ref="g", plugin_id="stella.sample.alpha", user_id="local-default",
                capabilities=["sample.ping"])
    session = PluginSession(root, source_label="test", registry=registry, authz=authz)
    errors = []

    def invoke():
        try:
            session.invoke_contract(contract="stella.sample.alpha@1", method="ping", input_payload={},
                                    origin="ui", grant_ref="g", timeout_ms=1200)
        except Exception as exc:
            errors.append(exc)

    session.start()
    process = session._proc
    thread = threading.Thread(target=invoke, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(3)
    finished = not thread.is_alive()
    if not finished:
        process.kill()
        thread.join(2)
    session.dispose()
    assert finished, "transport deadline did not release the caller"
    assert time.monotonic() - started < 4
    assert errors and "unknown" in str(errors[0]).lower()
    assert registry.get(session.plugin_id) is None
    assert process.poll() is not None


def test_plugin_stderr_flood_does_not_block_response(tmp_path, registry):
    import threading

    root = _runtime_fixture(tmp_path, '''import sys
def handle(method, params):
    sys.stderr.write("x" * 3_000_000)
    sys.stderr.flush()
    return {"status": "succeeded", "sideEffects": "none", "value": "ok"}
''')
    session = PluginSession(root, source_label="test", registry=registry)
    results = []
    session.start()
    thread = threading.Thread(target=lambda: results.append(session.invoke("ping")), daemon=True)
    thread.start()
    thread.join(4)
    finished = not thread.is_alive()
    if not finished:
        session._proc.kill()
        thread.join(2)
    session.dispose()
    assert finished, "stderr backpressure blocked RPC"
    assert results[0]["value"] == "ok"


def test_failed_prepare_cleans_up_worker(tmp_path, registry):
    root = _runtime_fixture(tmp_path, '''SERVICE_DESCRIPTORS = [{"contract": "stella.sample.alpha@1", "methods": [{}]}]
def handle(method, params):
    return {"status": "succeeded", "sideEffects": "none", "value": {}}
''')
    session = PluginSession(root, source_label="test", registry=registry)
    try:
        with pytest.raises((KeyError, ValueError)):
            session.start()
        assert session._proc is None
        assert registry.get(session.plugin_id) is None
    finally:
        session.dispose()


def test_starting_existing_session_does_not_dispose_active_worker(registry):
    from core.plugins.host import PluginHostError

    session = PluginSession(Path("samples/plugins/alpha"), source_label="test", registry=registry)
    try:
        session.start()
        process = session._proc
        with pytest.raises(PluginHostError, match="already started"):
            session.start()
        assert session._proc is process
        assert process.poll() is None
        assert session.invoke("ping")["status"] == "succeeded"
    finally:
        session.dispose()


def test_dispose_interrupts_an_inflight_worker_with_long_deadline(tmp_path, registry):
    import threading
    import time
    from core.plugins.authz import PluginAuthorizationStore

    marker = tmp_path / "entered"
    root = _runtime_fixture(tmp_path, f'''import time
from pathlib import Path
def handle(method, params):
    Path({str(marker)!r}).touch()
    time.sleep(60)
''')
    authz = PluginAuthorizationStore()
    session = PluginSession(root, source_label="test", registry=registry, authz=authz)
    authz.issue(grant_ref="g", plugin_id=session.plugin_id, user_id=session.user_id, capabilities=["sample.ping"])
    errors = []

    def invoke():
        try:
            session.invoke_contract(contract="stella.sample.alpha@1", method="ping", input_payload={},
                                    origin="ui", grant_ref="g", timeout_ms=60_000)
        except Exception as exc:
            errors.append(exc)

    session.start()
    process = session._proc
    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    disposer = threading.Thread(target=session.dispose, daemon=True)
    disposer.start()
    disposer.join(5)
    finished = not disposer.is_alive()
    if not finished:
        process.kill()
    thread.join(3)
    disposer.join(3)
    assert finished, "dispose waited for the entire invocation deadline"
    assert process.poll() is not None
    assert registry.get(session.plugin_id) is None
    assert errors and "unknown" in str(errors[0]).lower()
