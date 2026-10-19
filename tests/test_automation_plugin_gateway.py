from __future__ import annotations

import ast
import importlib.util
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.services import automation_gateway

WORKSPACE_ROOT = Path("stella-plugins-workspace/plugins/automation")
SIBLING_ROOT = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "automation"
AGENT = "agent-a"
USER = "u1"


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    monkeypatch.setenv("STELLA_AUTOMATION_PLUGIN", "1")
    monkeypatch.setenv("STELLA_AUTOMATION_PLUGIN_ROOT", str(WORKSPACE_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    yield
    automation_gateway.shutdown_automation_session()


def _plugin_roots():
    roots = [WORKSPACE_ROOT]
    if SIBLING_ROOT.is_dir():
        roots.append(SIBLING_ROOT)
    return roots


def _call(db, method, **params):
    return automation_gateway.invoke_automation(method, params, db_path=db, agent_id=AGENT, owner_user_id=USER)


def _ok(db, method, **params):
    result = _call(db, method, **params)
    assert result["status"] == "succeeded", result
    return result["value"]


def _task(task_id="t1", **extra):
    task = {"id": task_id, "name": "晨报", "enabled": True,
            "schedule": {"type": "interval", "seconds": 3600},
            "action": {"type": "send_message", "channel_type": "desktop", "receiver": "desktop",
                       "content": "早上好"},
            "next_run_at": (datetime.now() + timedelta(hours=1)).isoformat()}
    task.update(extra)
    return task


@pytest.mark.parametrize("root", _plugin_roots())
def test_plugin_package_has_no_host_agent_imports(root):
    offenders = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in {"agent", "common", "channel", "application", "core", "croniter"}:
                    offenders.append(f"{path}: {name}")
    assert offenders == []


def test_descriptors_match_gateway_table_and_permissions():
    spec = importlib.util.spec_from_file_location(
        "stella_automation_entry_for_test", WORKSPACE_ROOT / "backend" / "main.py")
    module = importlib.util.module_from_spec(spec)
    backend = str((WORKSPACE_ROOT / "backend").resolve())
    sys.path.insert(0, backend)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(backend)
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]
    descriptor = module.SERVICE_DESCRIPTORS[0]
    assert descriptor["contract"] == "stella.automation@1"
    methods = {m["name"]: m for m in descriptor["methods"]}
    assert set(methods) == set(automation_gateway.AUTOMATION_METHOD_PARAMS)
    for name, method in methods.items():
        assert tuple(method["inputSchema"]["properties"]) == automation_gateway.AUTOMATION_METHOD_PARAMS[name]
        expected = "automation.write" if name in automation_gateway.AUTOMATION_WRITE_METHODS else "automation.read"
        assert method["permissions"] == [expected]


def test_crud_and_structured_failures(tmp_path):
    db = tmp_path / "automation.db"
    created = _ok(db, "create_task", task=_task(), origin="user")
    assert created["owner_user_id"] == USER
    assert _ok(db, "get_task", task_id="t1")["name"] == "晨报"
    assert [t["id"] for t in _ok(db, "list_tasks", enabled_only=False)] == ["t1"]
    dup = _call(db, "create_task", task=_task(), origin="user")
    assert dup["status"] == "failed" and dup["error"]["code"] == "invalid_argument"
    missing = _call(db, "get_task", task_id="nope")
    assert missing["status"] == "failed" and missing["error"]["code"] == "not_found"
    assert _call(db, "delete_task", task_id="nope")["error"]["code"] == "not_found"
    assert _call(db, "create_task", task=_task("t2", schedule={"type": "cron", "expression": "bad"}),
                 origin="user")["error"]["code"] == "invalid_argument"
    assert _call(db, "create_task", task=_task("t3", schedule={"type": "interval", "seconds": 0}),
                 origin="user")["error"]["code"] == "invalid_argument"
    disabled = _ok(db, "enable_task", task_id="t1", enabled=False)
    assert disabled["enabled"] is False
    assert _call(db, "enable_task", task_id="t1", enabled="yes")["error"]["code"] == "invalid_argument"
    assert _ok(db, "list_tasks", enabled_only=True) == []
    assert _ok(db, "delete_task", task_id="t1")["id"] == "t1"
    assert _ok(db, "list_tasks", enabled_only=False) == []


def test_ownership_is_scoped_to_agent_and_user(tmp_path):
    db = tmp_path / "automation.db"
    _ok(db, "create_task", task=_task(), origin="user")
    other = automation_gateway.invoke_automation(
        "list_tasks", {"enabled_only": False}, db_path=db, agent_id=AGENT, owner_user_id="someone-else")
    assert other["value"] == []
    wrong_owner = _call(db, "create_task", task=_task("t9", owner_user_id="intruder"), origin="user")
    assert wrong_owner["status"] == "failed"
    foreign = _call(db, "create_task", task=_task("t8", owner_agent_id="agent-b"), origin="user")
    assert foreign["status"] == "failed" and "different Agent" in foreign["error"]["message"]


def test_run_permission_only_settable_by_user_origin(tmp_path):
    db = tmp_path / "automation.db"
    denied = _call(db, "create_task", task=_task(run_permission_mode="full-access"), origin="agent")
    assert denied["status"] == "failed" and "只有用户" in denied["error"]["message"]
    invalid = _call(db, "create_task", task=_task(run_permission_mode="root"), origin="user")
    assert invalid["error"]["code"] == "invalid_argument"
    ok = _ok(db, "create_task", task=_task(run_permission_mode="read-only"), origin="user")
    assert ok["run_permission_mode"] == "read-only"
    inherit = _ok(db, "update_task", task_id="t1", patch={"run_permission_mode": "inherit"}, resolved={},
                  origin="user")
    assert "run_permission_mode" not in inherit
    agent_attempt = _call(db, "update_task", task_id="t1", patch={"run_permission_mode": "full-access"},
                          resolved={}, origin="agent")
    assert agent_attempt["status"] == "failed"


def test_update_rules_linked_guard_allowed_fields_and_next_run(tmp_path):
    db = tmp_path / "automation.db"
    _ok(db, "create_task", task=_task(), origin="user")
    renamed = _ok(db, "update_task", task_id="t1", patch={"name": "新名字"}, resolved={}, origin="user")
    assert renamed["name"] == "新名字" and "updated_at" in renamed
    rescheduled = _ok(db, "update_task", task_id="t1",
                      patch={"schedule": {"type": "interval", "seconds": 120}}, resolved={}, origin="user")
    assert datetime.fromisoformat(rescheduled["next_run_at"]) < datetime.now() + timedelta(seconds=130)
    bad_field = _call(db, "update_task", task_id="t1", patch={"owner_user_id": "x"}, resolved={}, origin="user")
    assert bad_field["error"]["code"] == "invalid_argument"
    past = _call(db, "update_task", task_id="t1", patch={"schedule": {"type": "once", "run_at": "2000-01-01T00:00:00"}},
                 resolved={}, origin="user")
    assert past["status"] == "failed" and "next run" in past["error"]["message"]
    unresolved = _call(db, "update_task", task_id="t1", patch={"action": {"content": "x"}}, resolved={}, origin="user")
    assert unresolved["status"] == "failed" and "host" in unresolved["error"]["message"]
    resolved = _ok(db, "update_task", task_id="t1", patch={"action": {"content": "改"}},
                   resolved={"action": {"type": "send_message", "content": "改", "silent": True}}, origin="user")
    assert resolved["action"] == {"type": "send_message", "content": "改"}
    _ok(db, "create_task", task=_task("linked", linked_todo_id="todo-1"), origin="user")
    for method, params in (("update_task", {"patch": {"name": "x"}, "resolved": {}, "origin": "user"}),
                           ("delete_task", {}), ("enable_task", {"enabled": False})):
        guarded = _call(db, method, task_id="linked", **params)
        assert guarded["status"] == "failed" and "关联事务" in guarded["error"]["message"]


def test_calculate_next_run_matches_core_scheduler(tmp_path):
    from agent.scheduler.service import SchedulerService

    db = tmp_path / "automation.db"
    base = datetime(2026, 10, 19, 16, 7, 33)
    core = SchedulerService(object(), lambda _t: None)
    for schedule in (
        {"type": "cron", "expression": "0 9 * * 1-5"},
        {"type": "cron", "expression": "*/15 * * * *"},
        {"type": "cron", "expression": "30 8 * * * *"},
        {"type": "interval", "seconds": 90},
        {"type": "once", "run_at": "2026-10-20T08:00:00"},
        {"type": "once", "run_at": "2020-01-01T08:00:00"},
        {"type": "cron", "expression": "not a cron"},
        {"type": "interval", "seconds": 0},
    ):
        task = {"schedule": schedule}
        expected = core._calculate_next_run(task, base)
        got = _ok(db, "calculate_next_run", task=task, from_time=base.isoformat())
        assert got == (expected.isoformat() if expected else None), schedule


def test_plugin_cron_matches_croniter_over_random_instants():
    from agent.scheduler.cron import iter_cron

    path = (WORKSPACE_ROOT / "backend" / "domain" / "cron.py").resolve()
    spec = importlib.util.spec_from_file_location("stella_automation_cron_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rng = random.Random(7)
    expressions = [
        "0 9 * * *", "*/5 * * * *", "30 8 * * 1-5", "0 0 1 * *", "15 10 15 * mon", "0 */2 * * *",
        "0 0 * * 0", "0 0 * * 7", "10 30 8 * * *", "0 9,18 * * 1,3,5", "5/15 * * * *", "0 0 29 2 *",
        "0 12 * jan,jul *", "0 8 1-7 * 1", "*/30 9-17 * * 1-5", "0 0 31 * *",
    ]
    span = (datetime(2028, 12, 31) - datetime(2026, 1, 1)).total_seconds()
    for expression in expressions:
        for _ in range(25):
            start = datetime(2026, 1, 1) + timedelta(seconds=rng.random() * span)
            start = start.replace(microsecond=rng.choice([0, 500000]))
            assert module.next_cron(expression, start) == iter_cron(expression, start).get_next(datetime), (
                expression, start)
    for bad in ("", "* * *", "61 * * * *", "* * * * * * *", "*/0 * * * *", "5-1 * * * *"):
        with pytest.raises(ValueError):
            module.CronExpression(bad)


def test_resolve_handler_matches_legacy_scheduler_classification(tmp_path):
    db = tmp_path / "automation.db"
    cases = [
        {"action": {"type": "agent_task", "task_description": "x"}},
        {"action": {"type": "agent_task", "silent": True}},
        {"action": {"type": "send_message", "silent": True, "channel_type": "feishu", "receiver": "ou_1"}},
        {"action": {"type": "tool_call", "silent": True}},
        {"action": {"type": "application_command"}},
        {"action": {"type": "skill_call"}, "notification_route": {"primary": {"channel_type": "desktop"}}},
        {"action": {"type": "agent_task", "conversation_mode": "new"}},
        {"action": {"type": "mystery"}},
        {"action": {}},
    ]
    for task in cases:
        plan = _ok(db, "resolve_handler", task=task)
        action = task["action"]
        kind = action.get("type")
        silent = kind == "application_command" or (
            kind in ("agent_task", "tool_call", "skill_call") and action.get("silent", False))
        persist = "conversation_mode" in action
        assert plan["handler"] == kind
        assert plan["silent"] is bool(silent) and plan["persist_in_chat"] is persist
        assert plan["needs_channel_ready"] is (not silent and not task.get("notification_route") and not persist)
        assert plan["valid"] is (kind in {"agent_task", "send_message", "tool_call", "skill_call",
                                          "application_command"})


def _store(tmp_path):
    from agent.scheduler.automation_store import AutomationStore

    return AutomationStore(str(tmp_path / "scheduler" / "tasks.json"), AGENT)


@pytest.fixture
def identity():
    from common.runtime_identity import RuntimeIdentity, use_identity

    with use_identity(RuntimeIdentity(agent_id=AGENT, user_id=USER)):
        yield


def test_application_scheduler_routes_through_plugin_and_core_lease_still_works(tmp_path, identity):
    from application.api import Application
    from core.services.automation_facade import AutomationPluginFacade

    store = _store(tmp_path)
    scheduler = Application.scheduler(store)
    assert isinstance(scheduler, AutomationPluginFacade)
    route = {"primary": {"channel_type": "desktop", "receiver": "desktop"}}
    created = scheduler.create(
        _task(), notification_route=route, agent_id=AGENT)
    assert created["notification_route"]["primary"]["channel_type"] == "desktop"
    assert store.get_task("t1")["name"] == "晨报"  # Core store reads the plugin-written row
    listed = scheduler.list()
    assert [t["id"] for t in listed] == ["t1"] and "notification_delivery_status" in listed[0]
    assert listed[0]["notification_route"]["needs_reselect"] is False

    # Core still owns occurrence leases / delivery state for plugin-created tasks.
    run_id = store.claim_occurrence("t1", created["next_run_at"])
    assert run_id
    store.queue_delivery(run_id, "primary", "desktop", "desktop")
    assert scheduler.get("t1")["notification_delivery_status"]["status"] == "pending"
    store.finish_occurrence(run_id, True)

    updated = scheduler.update("t1", {"name": "改名", "enabled": False,
                                      "action": {"content": "新内容"}}, agent_id=AGENT)
    assert updated["name"] == "改名" and updated["enabled"] is False
    assert updated["action"]["content"] == "新内容"
    assert scheduler.enable("t1", True)["enabled"] is True
    with pytest.raises(ValueError):
        scheduler.get("missing")
    with pytest.raises(ValueError):
        scheduler.update("t1", {"bogus": 1}, agent_id=AGENT)
    with pytest.raises(ValueError):
        scheduler.update("t1", {"run_permission_mode": "full-access"}, agent_id=AGENT, origin="agent")
    with pytest.raises(ValueError):
        scheduler.enable("t1", "yes")
    assert scheduler.delete("t1")["id"] == "t1"
    assert store.list_tasks() == []
    with pytest.raises(ValueError):
        scheduler.delete("t1")


def test_facade_update_matches_legacy_mutations_for_route_changes(tmp_path, identity):
    from agent.scheduler.mutations import SchedulerMutations
    from core.services.automation_facade import AutomationPluginFacade

    legacy_store = _store(tmp_path / "legacy")
    plugin_store = _store(tmp_path / "plugin")
    legacy, plugin = SchedulerMutations(legacy_store), AutomationPluginFacade(plugin_store)
    route = {"primary": {"channel_type": "desktop", "receiver": "desktop"}}
    task = _task(next_run_at=(datetime.now() + timedelta(hours=1)).isoformat())
    for service in (legacy, plugin):
        service.create(dict(task), notification_route=route, agent_id=AGENT)
    patch = {"name": "B", "enabled": False,
             "notification_route": {"primary": {"channel_type": "desktop", "receiver": "desktop"}},
             "action": {"content": "更新"}}
    expected = legacy.update("t1", patch, agent_id=AGENT)
    got = plugin.update("t1", patch, agent_id=AGENT)
    volatile = {"updated_at", "next_run_at"}
    assert {k: v for k, v in got.items() if k not in volatile} == {
        k: v for k, v in expected.items() if k not in volatile}
    for service in (legacy, plugin):
        with pytest.raises(ValueError, match="备用渠道已移除"):
            service.update("t1", {"notification_route": {"primary": {"channel_type": "desktop"},
                                                          "backup": {"channel_type": "desktop"}}},
                           agent_id=AGENT)


def test_application_scheduler_keeps_legacy_json_store_on_core(tmp_path, identity):
    from agent.scheduler.mutations import SchedulerMutations
    from agent.scheduler.store import TaskStore
    from application.api import Application

    scheduler = Application.scheduler(TaskStore(str(tmp_path / "tasks.json")))
    assert isinstance(scheduler, SchedulerMutations)


def test_application_scheduler_refuses_automation_db_when_flag_off(tmp_path, identity, monkeypatch):
    """automation.db is plugin-owned; flag off must fail closed (not Core mutations)."""
    from application.api import Application

    monkeypatch.delenv("STELLA_AUTOMATION_PLUGIN", raising=False)
    monkeypatch.setenv("STELLA_AUTOMATION_PLUGIN", "0")
    with pytest.raises(RuntimeError, match="requires the stella.automation plugin"):
        Application.scheduler(_store(tmp_path))


def test_scheduler_handler_plan_uses_plugin_and_falls_back_on_failure(tmp_path, identity, monkeypatch):
    from agent.scheduler import integration

    store = _store(tmp_path)
    task = _task(action={"type": "application_command", "domain": "todos"})
    plan = integration._handler_plan(task, store, AGENT)
    assert plan["handler"] == "application_command" and plan["silent"] is True
    assert plan["needs_channel_ready"] is False

    called = []

    def boom(*args, **kwargs):
        called.append(1)
        raise RuntimeError("worker down")

    monkeypatch.setattr(automation_gateway, "resolve_handler", boom)
    fallback = integration._handler_plan(_task(), store, AGENT)
    assert called and fallback["handler"] == "send_message" and fallback["needs_channel_ready"] is True

    monkeypatch.delenv("STELLA_AUTOMATION_PLUGIN")
    called.clear()
    assert integration._handler_plan(_task(), store, AGENT)["handler"] == "send_message"
    assert called == []


def test_automation_migration_entry_applies_and_verifies(tmp_path):
    path = (WORKSPACE_ROOT / "backend" / "migrate.py").resolve()
    spec = importlib.util.spec_from_file_location("stella_automation_migrate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handle = {"dbPath": str(tmp_path / "automation.db")}
    assert module.verify("m1", handle)["verified"] is False
    assert module.apply("m1", handle)["applied"] is True
    assert module.apply("m1", handle)["applied"] is True
    verified = module.verify("m1", handle)
    assert verified["verified"] is True and verified["missingTables"] == []


def test_commit_automation_package_and_invoke_service(tmp_path):
    from core.plugins.host import PluginSession
    from core.plugins.package_ops import PackageStage, PackageStore
    from core.plugins.runtime_hub import DEFAULT_REGISTRY

    store = PackageStore(tmp_path / "pkg")
    op = store.stage(WORKSPACE_ROOT)
    op = store.inspect(op.operation_id)
    op = store.prepare(op.operation_id)
    op = store.commit(op.operation_id)
    assert op.stage == PackageStage.COMMITTED
    current = store.current_package("stella.automation")
    session = PluginSession(Path(current["path"]), source_label="local-cache", registry=DEFAULT_REGISTRY)
    try:
        assert session.start()["initialize"]["pluginId"] == "stella.automation"
        handle = {"dbPath": str(tmp_path / "a.db"), "agentId": AGENT, "userId": ""}
        listed = session.invoke("list_tasks", {"_dataHandle": handle})
        assert listed["status"] == "succeeded" and listed["value"] == []
    finally:
        session.dispose()


def test_official_catalog_digest_matches_automation_package():
    from core.plugins.distribution import verify_package_digest

    catalog = SIBLING_ROOT.parents[1] / "catalog" / "official.json"
    if not catalog.is_file() or not SIBLING_ROOT.is_dir():
        pytest.skip("Stella-Plugins checkout not present")
    entry = next(e for e in json.loads(catalog.read_text())["plugins"] if e["pluginId"] == "stella.automation")
    assert verify_package_digest(SIBLING_ROOT, entry["sha256"])
