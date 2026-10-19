from __future__ import annotations

import ast
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.services import todos_gateway

WORKSPACE_ROOT = Path("stella-plugins-workspace/plugins/tasks")
SIBLING_ROOT = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "tasks"


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    monkeypatch.setenv("STELLA_TODOS_PLUGIN_ROOT", str(WORKSPACE_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    monkeypatch.setenv("STELLA_TODOS_PLUGIN_SCHEDULER_SYNC", "0")
    yield
    todos_gateway.shutdown_todos_session()


def _plugin_roots():
    roots = [WORKSPACE_ROOT]
    if SIBLING_ROOT.is_dir():
        roots.append(SIBLING_ROOT)
    return roots


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
                if name.split(".")[0] in {"agent", "common", "channel", "application"}:
                    offenders.append(f"{path}: {name}")
    assert offenders == []


def test_descriptors_cover_application_todo_methods_and_gateway_table():
    from application.api import _METHODS

    spec = importlib.util.spec_from_file_location(
        "stella_tasks_entry_for_test", WORKSPACE_ROOT / "backend" / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str((WORKSPACE_ROOT / "backend").resolve()))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str((WORKSPACE_ROOT / "backend").resolve()))
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]
    descriptor = module.SERVICE_DESCRIPTORS[0]
    assert descriptor["contract"] == "stella.tasks@1"
    methods = {m["name"]: m for m in descriptor["methods"]}
    assert set(_METHODS["todos"]) <= set(methods)
    assert set(methods) == set(todos_gateway.TODOS_METHOD_PARAMS)
    for name, method in methods.items():
        assert tuple(method["inputSchema"]["properties"]) == todos_gateway.TODOS_METHOD_PARAMS[name]
        expected = "tasks.write" if name in todos_gateway.TODOS_WRITE_METHODS else "tasks.read"
        assert method["permissions"] == [expected]


def test_todos_plugin_create_and_list(tmp_path):
    db = tmp_path / "todos.db"
    created = todos_gateway.invoke_todos(
        "create_todo",
        {"payload": {"title": "写周报", "due_on": "2026-10-20", "priority": 2}},
        db_path=db,
    )
    assert created["status"] == "succeeded"
    assert created["value"]["title"] == "写周报"
    listed = todos_gateway.invoke_todos("list_todos", {}, db_path=db)
    assert listed["status"] == "succeeded"
    assert [row["title"] for row in listed["value"]] == ["写周报"]


def test_unknown_param_and_missing_todo_are_structured_failures(tmp_path):
    db = tmp_path / "todos.db"
    missing = todos_gateway.invoke_todos("get_todo", {"todo_id": "nope"}, db_path=db)
    assert missing["status"] == "failed"
    assert missing["error"]["code"] == "not_found"
    invalid = todos_gateway.invoke_todos("create_todo", {"payload": {"title": ""}}, db_path=db)
    assert invalid["status"] == "failed"
    assert invalid["error"]["code"] == "invalid_argument"


def _patch_paths(monkeypatch, tmp_path):
    from core.services import todos_facade

    monkeypatch.setattr(
        todos_facade, "_db_paths", lambda: (tmp_path / "todos.db", tmp_path / "calendar.db")
    )


def test_application_port_routes_todos_via_plugin(tmp_path, monkeypatch):
    from application.api import Application
    from common.runtime_identity import RuntimeIdentity, use_identity

    _patch_paths(monkeypatch, tmp_path)
    with use_identity(RuntimeIdentity(agent_id="test-agent", user_id="test-user")):
        port = Application.port("todos")
        todo = port.create_todo({"title": "买菜", "due_on": "2026-10-21"})
        assert todo["status"] == "todo"
        child = port.add_subtask(todo["id"], {"title": "牛奶"})
        assert child["parent_id"] == todo["id"]
        done = port.complete_todo(child["id"], True)
        assert done["status"] == "completed"
        assert port.get_todo(todo["id"])["progress_completed"] == 1
        category = port.create_category({"name": "家务", "color": "#112233"})
        assert port.set_todo_category(todo["id"], category["id"])["list_name"] == "家务"
        assert [c["name"] for c in port.categories()] == ["家务"]
        with pytest.raises(KeyError):
            port.get_todo("missing")
        with pytest.raises(ValueError):
            port.create_todo({"title": " "})
        assert port.delete_todo(todo["id"]) is None
        assert port.list_todos() == []


def test_reminder_claim_and_ack_work_against_local_tables(tmp_path, monkeypatch):
    from core.services.todos_facade import TodosPluginFacade

    _patch_paths(monkeypatch, tmp_path)
    facade = TodosPluginFacade()
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    todo = facade.create_todo({"title": "喝水", "remind_at": past})
    claims = facade.claim_desktop_reminders(datetime.now(timezone.utc), 5)
    assert [c["todo_id"] for c in claims] == [todo["id"]]
    assert facade.acknowledge_desktop_reminder(claims[0]["delivery_id"], claims[0]["claim_id"], True) is True
    assert facade.claim_desktop_reminders() == []


def test_reminder_sync_is_noop_without_adapter_and_link_stays_pending(tmp_path, monkeypatch):
    from core.services.todos_facade import TodosPluginFacade

    _patch_paths(monkeypatch, tmp_path)
    facade = TodosPluginFacade()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    todo = facade.create_todo({"title": "开会", "remind_at": future})
    assert todo["reminder_sync_pending"] is True
    result = todos_gateway.invoke_todos(
        "pending_scheduler_links", {}, db_path=tmp_path / "todos.db"
    )
    assert [row["todo_id"] for row in result["value"]] == [todo["id"]]


def test_host_reconciles_pending_links_with_scheduler_store(tmp_path, monkeypatch):
    from agent.todos import scheduler_link
    from core.services.todos_facade import TodosPluginFacade

    class FakeStore:
        def __init__(self):
            self.tasks = {}

        def get_task(self, task_id):
            return self.tasks.get(task_id)

        def add_task(self, task):
            self.tasks[task["id"]] = task

        def update_task(self, task_id, task):
            self.tasks[task_id] = task

        def delete_task(self, task_id):
            self.tasks.pop(task_id, None)

    store = FakeStore()
    monkeypatch.setenv("STELLA_TODOS_PLUGIN_SCHEDULER_SYNC", "1")
    monkeypatch.setattr(scheduler_link, "default_scheduler_store", lambda: store)
    _patch_paths(monkeypatch, tmp_path)
    facade = TodosPluginFacade()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    todo = facade.create_todo({"title": "开会", "remind_at": future})
    assert f"todo-reminder:{todo['id']}" in store.tasks
    assert facade.get_todo(todo["id"])["reminder_sync_pending"] is False


def _load_vendored_domain():
    root = (WORKSPACE_ROOT / "backend" / "domain").resolve()
    spec = importlib.util.spec_from_file_location(
        "stella_tasks_domain_under_test",
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    return importlib.import_module(spec.name + ".service")


def test_vendored_service_dispatch_is_noop_without_adapter_and_uses_callback(tmp_path):
    service_module = _load_vendored_domain()
    expected = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0)
    route = {"primary": {"channel_type": "desktop", "receiver": "desktop"}}
    svc = service_module.TodoService(tmp_path / "todos.db")
    todo = svc.create_todo({
        "title": "提醒", "remind_at": expected.isoformat(), "reminder_delivery": route})
    assert svc.queue_scheduled_reminder(todo["id"], expected.isoformat()) is True
    assert svc.dispatch_scheduled_reminder(todo["id"], expected.isoformat()) is None

    calls = []

    def dispatcher(store, delivery_id, route, content, *, expires_at=None):
        calls.append((delivery_id, content))
        return "sent"

    wired = service_module.TodoService(tmp_path / "todos.db", notification_dispatcher=dispatcher)
    assert wired.dispatch_scheduled_reminder(todo["id"], expected.isoformat()) == "sent"
    assert calls and calls[0][1] == "事务提醒：提醒"


def _scheduler_context():
    from application import RequestContext

    return RequestContext(source="scheduler", user_id="test-user", agent_id="test-agent", session_id="s")


def _telegram_sends(monkeypatch):
    from types import SimpleNamespace

    from agent.scheduler import delivery

    monkeypatch.setattr(delivery, "runtime_channel", lambda _: SimpleNamespace(
        login_status="logged_in", _context_tokens={}))
    sends = []
    monkeypatch.setattr("agent.scheduler.dispatch._channel_for", lambda name: SimpleNamespace(
        send=lambda reply, context: sends.append((name, context["receiver"], reply.content)) or True))
    return sends


def test_scheduled_reminder_is_delivered_once_through_plugin_outbox(tmp_path, monkeypatch):
    from application import Application
    from core.services.todos_facade import TodosPluginFacade

    _patch_paths(monkeypatch, tmp_path)
    sends = _telegram_sends(monkeypatch)
    route = {"primary": {"channel_type": "telegram", "receiver": "100", "is_group": False}}
    due = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(microsecond=0).isoformat()
    facade = TodosPluginFacade()
    todo = facade.create_todo({"title": "Submit", "remind_at": due, "reminder_delivery": route})
    assert facade.queue_scheduled_reminder(todo["id"], due) is True

    first = Application.dispatch_todo_reminder(todo["id"], due, _scheduler_context())
    second = Application.dispatch_todo_reminder(todo["id"], due, _scheduler_context())

    assert first.status == "accepted" and second.status == "accepted"
    assert sends == [("telegram", "100", "事务提醒：Submit")]
    assert facade.claim_desktop_reminders() == []
    assert facade.get_todo(todo["id"])["reminder_delivery_status"]["status"] == "accepted"


def test_late_scheduled_reminder_expires_in_plugin_outbox_without_sending(tmp_path, monkeypatch):
    from application import Application
    from core.services.todos_facade import TodosPluginFacade

    _patch_paths(monkeypatch, tmp_path)
    sends = _telegram_sends(monkeypatch)
    route = {"primary": {"channel_type": "telegram", "receiver": "100", "is_group": False}}
    due = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0).isoformat()
    facade = TodosPluginFacade()
    todo = facade.create_todo({"title": "Old", "remind_at": due, "reminder_delivery": route})
    assert facade.queue_scheduled_reminder(todo["id"], due) is True

    assert Application.dispatch_todo_reminder(todo["id"], due, _scheduler_context()).status == "expired"
    assert sends == []
    assert facade.get_todo(todo["id"])["reminder_delivery_status"]["status"] == "expired"
