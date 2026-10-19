"""Frozen runner must ship stdlib modules business plugins need (R01 / G5)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNNER_SPEC = REPO / "desktop" / "build" / "stella-plugin-runner.spec"


def _pyinstaller() -> str | None:
    env = os.environ.get("STELLA_PYINSTALLER_PATH")
    if env and Path(env).is_file():
        return env
    return shutil.which("pyinstaller")


@pytest.fixture(scope="module")
def frozen_runner(tmp_path_factory) -> Path:
    pyi = _pyinstaller()
    if not pyi:
        pytest.skip("PyInstaller not available")
    work = tmp_path_factory.mktemp("runner-stdlib-build")
    dist = work / "dist"
    proc = subprocess.run(
        [
            pyi,
            str(RUNNER_SPEC),
            "--noconfirm",
            "--distpath",
            str(dist),
            "--workpath",
            str(work / "work"),
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    binary = dist / "stella-plugin-runner" / "stella-plugin-runner"
    if sys.platform == "win32":
        binary = dist / "stella-plugin-runner" / "stella-plugin-runner.exe"
    assert binary.is_file()
    return binary


def _write_sqlite_plugin(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "manifestVersion": 1,
                "id": "stella.sample.sqlite",
                "name": "sqlite probe",
                "version": "1.0.0",
                "hostApi": "^1.0.0",
                "runtime": {"kind": "python", "entry": "backend/main.py", "abi": "cp312"},
                "contributes": {"services": ["stella.sample.sqlite@1"]},
                "permissions": [{"capability": "sample.probe", "required": True}],
            }
        ),
        encoding="utf-8",
    )
    backend = root / "backend"
    backend.mkdir()
    (backend / "main.py").write_text(
        "import sqlite3\n"
        "SERVICE_DESCRIPTORS = [{'contract': 'stella.sample.sqlite@1', 'methods': "
        "[{'name': 'probe', 'permissions': ['sample.probe']}]}]\n"
        "\n"
        "def handle(method, params):\n"
        "    if method == 'probe':\n"
        "        return {\n"
        "            'status': 'succeeded',\n"
        "            'sideEffects': 'none',\n"
        "            'value': {'ok': True, 'sqlite': sqlite3.sqlite_version},\n"
        "        }\n"
        "    return {\n"
        "        'status': 'failed',\n"
        "        'sideEffects': 'none',\n"
        "        'error': {'code': 'not_found', 'message': method},\n"
        "    }\n",
        encoding="utf-8",
    )
    return root


def test_sqlite_probe_declares_the_invoked_method(tmp_path):
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry

    session = PluginSession(_write_sqlite_plugin(tmp_path / "probe"),
                            source_label="stdlib-probe", registry=PluginRegistry())
    try:
        session.start()
        assert session.invoke("probe")["value"]["ok"] is True
    finally:
        session.dispose()


def test_frozen_runner_can_import_sqlite3_for_plugin(frozen_runner, tmp_path, monkeypatch):
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry

    plugin = _write_sqlite_plugin(tmp_path / "sqlite-plugin")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    session = PluginSession(
        plugin,
        source_label="stdlib-probe",
        registry=PluginRegistry(),
        runner_command=[str(frozen_runner)],
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.sample.sqlite"
        result = session.invoke("probe", {})
        assert result["status"] == "succeeded"
        assert result["value"]["ok"] is True
        assert result["value"]["sqlite"]
    finally:
        session.dispose()


@pytest.mark.parametrize(
    "domain",
    ["bills", "tasks", "calendar", "email", "elearning", "briefing", "automation"],
)
def test_frozen_runner_initializes_default_domain_plugins(frozen_runner, domain, monkeypatch):
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry

    sibling = REPO.parent / "Stella-Plugins" / "plugins" / domain
    workspace = REPO / "stella-plugins-workspace" / "plugins" / domain
    root = sibling if sibling.is_dir() else workspace
    if not root.is_dir():
        pytest.skip(f"missing plugin package for {domain}")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    session = PluginSession(
        root,
        source_label=f"stdlib-{domain}",
        registry=PluginRegistry(),
        runner_command=[str(frozen_runner)],
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == f"stella.{domain}"
    finally:
        session.dispose()


@pytest.mark.parametrize("field", ["userId", "instanceId"])
def test_frozen_runner_rejects_forged_identity(frozen_runner, tmp_path, field):
    from datetime import datetime, timedelta, timezone
    from core.plugins.contract import build_host_context, build_invoke_params
    from core.plugins.host import PluginHostError, PluginSession
    from core.plugins.registry import PluginRegistry

    session = PluginSession(_write_sqlite_plugin(tmp_path / "probe"), source_label="frozen-probe",
                            registry=PluginRegistry(), runner_command=[str(frozen_runner)])
    try:
        session.start()
        context = build_host_context(user_id=session.user_id, instance_id=session.instance_id,
                                     generation=session.generation, origin="ui", grant_ref="g")
        context[field] = "forged"
        params = build_invoke_params(contract="stella.sample.sqlite@1", method="probe", input_payload={},
                                     context=context, deadline=datetime.now(timezone.utc) + timedelta(seconds=5))
        with pytest.raises(PluginHostError, match="identity mismatch"):
            session._rpc("plugin.invoke", params)
    finally:
        session.dispose()


def test_frozen_hung_worker_is_terminated_with_unknown_outcome(frozen_runner, tmp_path):
    import time
    from core.plugins.authz import PluginAuthorizationStore
    from core.plugins.host import PluginOutcomeUnknown, PluginSession
    from core.plugins.registry import PluginRegistry

    root = _write_sqlite_plugin(tmp_path / "hung")
    (root / "backend" / "main.py").write_text('''import time
SERVICE_DESCRIPTORS = [{"contract": "stella.sample.sqlite@1", "methods": [
    {"name": "probe", "effect": "domainWrite", "permissions": ["sample.probe"]}]}]
def handle(method, params):
    time.sleep(60)
''')
    authz = PluginAuthorizationStore()
    registry = PluginRegistry()
    session = PluginSession(root, source_label="frozen-probe", registry=registry, authz=authz,
                            runner_command=[str(frozen_runner)])
    authz.issue(grant_ref="g", plugin_id=session.plugin_id, user_id=session.user_id, capabilities=["sample.probe"])
    try:
        session.start()
        process = session._proc
        started = time.monotonic()
        with pytest.raises(PluginOutcomeUnknown, match="unknown"):
            session.invoke_contract(contract="stella.sample.sqlite@1", method="probe", input_payload={},
                                    origin="ui", grant_ref="g", timeout_ms=1200)
        assert time.monotonic() - started < 4
        assert process.poll() is not None
        assert registry.get(session.plugin_id) is None
    finally:
        session.dispose()


def test_frozen_maintenance_runner_applies_and_verifies_actual_schema(frozen_runner, tmp_path, monkeypatch):
    import sqlite3
    from core.plugins.host import PluginHostError, PluginSession
    from core.plugins.registry import PluginRegistry

    monkeypatch.setenv('PATH', '/nonexistent')
    monkeypatch.delenv('PYTHONPATH', raising=False)
    registry = PluginRegistry()
    session = PluginSession(REPO / 'stella-plugins-workspace/plugins/bills', source_label='frozen-migration',
                            registry=registry, maintenance=True, runner_command=[str(frozen_runner)])
    handle = {'namespace': 'stella.bills', 'dbPath': str(tmp_path / 'bills.sqlite')}
    try:
        session.start()
        assert registry.get(session.plugin_id) is None
        for mode in ('apply', 'verify'):
            result = session.migrate(operation_id='op', migration_id='migration', from_schema=0, to_schema=1,
                                     data_handle=handle, mode=mode)
            assert result['committed'] and result['verified']
        with sqlite3.connect(handle['dbPath']) as db:
            assert db.execute("SELECT name FROM sqlite_master WHERE name='financial_events'").fetchone()
        with pytest.raises(PluginHostError, match='maintenance'):
            session._rpc('plugin.invoke', {})
    finally:
        session.dispose()


def test_worker_does_not_write_bytecode_into_immutable_package(tmp_path, monkeypatch):
    from core.plugins.host import PluginSession, _digest_tree
    from core.plugins.package_ops import _sha256_tree
    from core.plugins.registry import PluginRegistry

    monkeypatch.delenv('PYTHONDONTWRITEBYTECODE', raising=False)
    root = _write_sqlite_plugin(tmp_path / 'immutable')
    digest = _sha256_tree(root)
    session = PluginSession(root, source_label='immutable', registry=PluginRegistry())
    try:
        session.start()
        session.invoke('probe')
        assert not list(root.rglob('*.pyc'))
        assert _digest_tree(root) == digest
    finally:
        session.dispose()


def test_frozen_worker_can_call_only_the_bound_public_core_channel(frozen_runner, tmp_path, monkeypatch):
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry
    from core.plugins import core_invoke
    from core.plugins.caller import current_consumer_plugin

    root = _write_sqlite_plugin(tmp_path / 'callback')
    (root / 'backend/main.py').write_text('''from stella_host import invoke
SERVICE_DESCRIPTORS = [{'contract':'stella.sample.sqlite@1', 'methods':[{'name':'probe', 'permissions':['sample.probe']}]}]
def handle_invoke(params):
    return invoke('stella.sample.target@1','read',{})
''')
    monkeypatch.setitem(core_invoke.PUBLIC_SERVICES, 'stella.sample.target@1',
        lambda *_: {'status':'succeeded','sideEffects':'none','value':{'consumer':current_consumer_plugin()}})
    session = PluginSession(root, source_label='frozen-callback', registry=PluginRegistry(), runner_command=[str(frozen_runner)])
    try:
        session.start()
        assert session.invoke('probe')['value']['consumer'] == 'stella.sample.sqlite'
    finally:
        session.dispose()
