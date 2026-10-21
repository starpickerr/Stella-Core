from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry


def test_revoked_grant_blocks_invoke():
    authz = PluginAuthorizationStore()
    registry = PluginRegistry()
    session = PluginSession(
        Path("samples/plugins/alpha"),
        source_label="sample",
        registry=registry,
        user_id="u1",
        authz=authz,
    )
    authz.issue(
        grant_ref="g1",
        plugin_id="stella.sample.alpha",
        user_id="u1",
        capabilities=["sample.ping"],
    )
    try:
        session.start()
        authz.revoke("g1")
        with pytest.raises(PermissionError, match="revoked"):
            session.invoke_contract(
                contract="stella.sample.alpha@1",
                method="ping",
                input_payload={},
                origin="ui",
                grant_ref="g1",
                permissions=["sample.ping"],
            )
    finally:
        session.dispose()


def test_missing_capability_denied():
    authz = PluginAuthorizationStore()
    assert authz.get("missing") is None
    with pytest.raises(PermissionError, match="unknown grantRef"):
        authz.check(
            grant_ref="missing",
            plugin_id="stella.sample.alpha",
            user_id="u1",
            required_capabilities=["sample.ping"],
            purpose="interactive",
            generation=1,
            context_generation=1,
        )


@pytest.mark.parametrize("domain", ["bills", "todos", "calendar", "briefing", "automation"])
def test_gateway_worker_restart_does_not_restore_revoked_grant(domain, monkeypatch):
    import importlib

    gateway = importlib.import_module(f"core.services.{domain}_gateway")
    shutdown = getattr(gateway, f"shutdown_{domain}_session")
    ensure = getattr(gateway, f"ensure_{domain}_session")
    authz = PluginAuthorizationStore()
    shutdown()
    monkeypatch.setattr(gateway, "DEFAULT_AUTHZ", authz)
    monkeypatch.setattr("core.plugins.host.DEFAULT_AUTHZ", authz)
    monkeypatch.setattr(gateway, "DEFAULT_REGISTRY", PluginRegistry())
    try:
        ensure()
        grant_ref = gateway._GRANT_REF
        authz.revoke(grant_ref)
        shutdown()
        session = ensure()
        with pytest.raises(PermissionError, match="revoked"):
            session.authz.check(grant_ref=grant_ref, plugin_id=session.plugin_id,
                                user_id=session.user_id, required_capabilities=[],
                                purpose="interactive", generation=session.generation,
                                context_generation=session.generation)
    finally:
        shutdown()




def test_grants_survive_application_restart_without_restoring_revocation(tmp_path):
    path = tmp_path / "authorization.sqlite"
    first = PluginAuthorizationStore(path=path)
    first.issue(grant_ref="durable", plugin_id="stella.bills", user_id="u1",
                capabilities=["bills.read"], purposes=["interactive", "background"])
    first.revoke("durable")
    restarted = PluginAuthorizationStore(path=path)
    grant = restarted.issue(grant_ref="durable", plugin_id="stella.bills", user_id="u1",
                            capabilities=["bills.read", "bills.write"], replace_existing=False)
    assert grant.revoked
    restarted.set_purposes("durable", ["interactive"])
    assert first.get("durable").purposes == frozenset({"interactive"})
    assert first.get("durable").revoked


def test_durable_grant_instances_do_not_overwrite_each_other(tmp_path):
    path = tmp_path / "authorization.sqlite"
    first = PluginAuthorizationStore(path=path)
    second = PluginAuthorizationStore(path=path)
    first.issue(grant_ref="a", plugin_id="stella.bills", user_id="u1", capabilities=["bills.read"])
    second.issue(grant_ref="b", plugin_id="stella.calendar", user_id="u1", capabilities=["calendar.read"])
    first.revoke("a")
    assert second.get("a").revoked
    assert first.get("b").plugin_id == "stella.calendar"


def test_system_origin_cannot_hide_ambient_tool_identity(monkeypatch):
    from common.runtime_identity import identity_scope

    session = PluginSession(Path("samples/plugins/alpha"), source_label="test", registry=PluginRegistry(),
                            authz=PluginAuthorizationStore())
    session.authz.issue(grant_ref="tool", plugin_id=session.plugin_id, user_id=session.user_id,
                        capabilities=["sample.ping"], purposes=["interactive", "tool", "job"])
    calls = []

    def deny(**kwargs):
        calls.append(kwargs)
        return "conversation denied"

    monkeypatch.setattr("core.plugins.host._conversation_permission_denial", deny)
    try:
        session.start()
        with identity_scope(agent_id="a1", session_id="s1"):
            with pytest.raises(PermissionError, match="conversation denied"):
                session.invoke_contract(contract="stella.sample.alpha@1", method="ping", input_payload={},
                                        origin="system", grant_ref="tool")
        assert calls[0]["agent_id"] == "a1"
        assert calls[0]["session_id"] == "s1"
    finally:
        session.dispose()


def test_permission_adapter_failure_is_closed(monkeypatch):
    import builtins
    from core.plugins.host import _conversation_permission_denial

    original = builtins.__import__

    def failing(name, *args, **kwargs):
        if name == "agent.runtime.tool_invocation":
            raise ImportError("unavailable permission adapter")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing)
    assert _conversation_permission_denial(contract="stella.bills@1", method="create_ledger",
                                           agent_id="a1", session_id="s1")


@pytest.mark.parametrize("contract,method,tool,action", [
    ("stella.tasks@1", "create_todo", "todos", "create"),
    ("stella.calendar@1", "create_event", "calendar", "create"),
    ("stella.briefing@1", "update_action", "briefing", "decide"),
    ("stella.automation@1", "create_task", "scheduler", "create"),
])
def test_plugin_method_maps_to_existing_permission_action(monkeypatch, contract, method, tool, action):
    from core.plugins.host import _conversation_permission_denial
    captured = []

    def check(name, arguments, **kwargs):
        captured.append((name, arguments, kwargs))
        return "denied"

    monkeypatch.setattr("agent.runtime.tool_invocation.permission_denial", check)
    assert _conversation_permission_denial(contract=contract, method=method, agent_id="a", session_id="s",
                                           input_payload={"payload": {"title": "example"}}, noninteractive=True)
    assert captured[0][0] == tool
    assert captured[0][1]["action"] == action
    assert captured[0][2]["noninteractive"] is True


def test_revocation_is_visible_to_a_fresh_python_process(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "authorization.sqlite"
    authz = PluginAuthorizationStore(path=path)
    authz.issue(grant_ref="g", plugin_id="stella.bills", user_id="u1", capabilities=["bills.read"])
    authz.revoke("g")
    result = subprocess.run([sys.executable, "-c", '''
import sys
from pathlib import Path
from core.plugins.authz import PluginAuthorizationStore
store = PluginAuthorizationStore(path=Path(sys.argv[1]))
grant = store.issue(grant_ref="g", plugin_id="stella.bills", user_id="u1",
                    capabilities=["bills.read", "bills.write"], replace_existing=False)
assert grant.revoked
assert grant.capabilities == frozenset({"bills.read"})
''', str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_gateway_switches_users_without_sharing_grants(monkeypatch):
    from common.runtime_identity import identity_scope
    from core.plugins.caller import user_grant_ref
    from core.services import bills_gateway as gateway

    authz = PluginAuthorizationStore()
    registry = PluginRegistry()
    gateway.shutdown_bills_session()
    monkeypatch.setattr(gateway, "DEFAULT_AUTHZ", authz)
    monkeypatch.setattr(gateway, "DEFAULT_REGISTRY", registry)
    try:
        with identity_scope(user_id="alice"):
            alice = gateway.ensure_bills_session()
            authz.revoke(user_grant_ref(gateway._GRANT_REF))
        with identity_scope(user_id="bob"):
            bob = gateway.ensure_bills_session()
            assert bob is not alice
            assert bob.user_id == "bob"
            assert alice._proc is None
            assert not authz.get(user_grant_ref(gateway._GRANT_REF)).revoked
        with identity_scope(user_id="alice"):
            restarted = gateway.ensure_bills_session()
            assert restarted.user_id == "alice"
            assert restarted.generation > alice.generation
            assert authz.get(user_grant_ref(gateway._GRANT_REF)).revoked
    finally:
        gateway.shutdown_bills_session()




def test_application_port_keeps_scheduled_identity(monkeypatch):
    from common.runtime_identity import current_identity, identity_scope
    from application import Application, RequestContext
    from types import SimpleNamespace

    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "1")
    monkeypatch.setattr("core.services.bills_facade.BillsPluginFacade",
                        lambda: SimpleNamespace(get_ledger=lambda *args: current_identity()))
    with identity_scope(task_id="job-1", execution_session_id="execution-1", run_id="run-1"):
        port = Application.port("bills", RequestContext(user_id="local-default", source="scheduler"))
        identity = port.get_ledger("ledger-1")
    assert identity.task_id == "job-1"
    assert identity.execution_session_id == "execution-1"
    assert identity.run_id == "run-1"


def test_tool_origin_does_not_change_explicit_operation_purpose(monkeypatch):
    from common.runtime_identity import identity_scope

    session = PluginSession(Path("samples/plugins/alpha"), source_label="test", registry=PluginRegistry(),
                            authz=PluginAuthorizationStore())
    session.authz.issue(grant_ref="read", plugin_id=session.plugin_id, user_id=session.user_id,
                        capabilities=["sample.ping"], purposes=["interactive"])
    checked = []
    monkeypatch.setattr("core.plugins.host._conversation_permission_denial", lambda **kw: checked.append(kw))
    try:
        session.start()
        with identity_scope(agent_id="agent", session_id="session"):
            result = session.invoke_contract(contract="stella.sample.alpha@1", method="ping", input_payload={},
                                             origin="system", grant_ref="read", purpose="interactive")
        assert result["status"] == "succeeded"
        assert checked[0]["session_id"] == "session"
    finally:
        session.dispose()


@pytest.mark.parametrize("contract,method", [
    ("stella.tasks@1", "create_category"), ("stella.tasks@1", "set_todo_category"),
    ("stella.calendar@1", "ingest_briefing_revision"),
    ("stella.briefing@1", "run_pipeline"), ("stella.briefing@1", "stage_source_items"),
    ("stella.briefing@1", "set_cursor"), ("stella.briefing@1", "upsert_source_item"),
    ("stella.automation@1", "sync_reminders"),
])
def test_unmapped_plugin_mutations_cannot_be_classified_as_reads(monkeypatch, tmp_path, contract, method):
    from agent.permission.gateway import SecurityGateway, Scope
    from core.plugins.host import _conversation_permission_denial

    def actual_policy(name, arguments, **kwargs):
        result = SecurityGateway.check("read-only", name, arguments, cwd=str(tmp_path),
                                       scope=Scope(write_roots=(str(tmp_path),)), create_pending=False)
        return None if result.allowed else result.reason

    monkeypatch.setattr("agent.runtime.tool_invocation.permission_denial", actual_policy)
    assert _conversation_permission_denial(contract=contract, method=method, agent_id=None, session_id=None,
                                           effect="domainWrite")


@pytest.mark.parametrize("domain", ["bills", "todos", "calendar", "briefing", "automation"])
def test_gateway_replaces_dead_worker_without_regranting_or_replaying(domain, monkeypatch):
    import importlib

    gateway = importlib.import_module(f"core.services.{domain}_gateway")
    shutdown = getattr(gateway, f"shutdown_{domain}_session")
    ensure = getattr(gateway, f"ensure_{domain}_session")
    authz = PluginAuthorizationStore()
    shutdown()
    monkeypatch.setattr(gateway, "DEFAULT_AUTHZ", authz)
    monkeypatch.setattr(gateway, "DEFAULT_REGISTRY", PluginRegistry())
    try:
        first = ensure()
        first._proc.kill()
        first._proc.wait(timeout=3)
        authz.revoke(gateway._GRANT_REF)
        second = ensure()
        assert second is not first
        assert second.generation > first.generation
        assert second._proc.poll() is None
        assert authz.get(gateway._GRANT_REF).revoked
    finally:
        shutdown()


def test_unrelated_plugin_gateways_do_not_wait_for_each_other():
    import threading
    from core.plugins.caller import serialized_gateway

    entered = threading.Event()
    release = threading.Event()
    second_finished = threading.Event()

    def slow():
        entered.set()
        release.wait(3)

    def fast():
        second_finished.set()

    slow.__module__ = "core.services.slow_gateway"
    fast.__module__ = "core.services.fast_gateway"
    first = threading.Thread(target=serialized_gateway(slow), daemon=True)
    second = threading.Thread(target=serialized_gateway(fast), daemon=True)
    first.start()
    assert entered.wait(1)
    second.start()
    proceeded = second_finished.wait(1)
    release.set()
    first.join(2)
    second.join(2)
    assert proceeded, "an unrelated slow connector blocked this plugin"


def test_default_port_context_does_not_erase_ambient_task_origin(monkeypatch):
    from common.runtime_identity import identity_scope
    from application import Application
    from core.plugins.caller import current_caller_origin
    from types import SimpleNamespace

    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "1")
    monkeypatch.setattr("core.services.bills_facade.BillsPluginFacade",
                        lambda: SimpleNamespace(get_ledger=lambda *args: current_caller_origin()))
    with identity_scope(task_id="job-1"):
        assert Application.port("bills").get_ledger("ledger-1") == "job"


@pytest.fixture(autouse=True)
def isolated_execution_workspace(tmp_path, monkeypatch):
    # These authorization tests deliberately use synthetic Agent IDs. Keep
    # their host execution context independent of the real Agent registry.
    monkeypatch.setattr('agent.workspace.context.personal_work_dir', lambda **_: tmp_path / 'work')
