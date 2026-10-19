"""G5 legacy-exit guards: default business domains live in plugin packages, not in Core's frozen app.

These are static/structural checks. They do not prove CSP e2e, signed ZIPs, DMG runner
integration or deletion of the old ``agent.*`` services (see the G5 blockers list).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKSPACE = REPO / "stella-plugins-workspace" / "plugins"
SIBLING = REPO.parent / "Stella-Plugins" / "plugins"
BACKEND_SPEC = REPO / "desktop" / "build" / "stella-backend.spec"
RUNNER_SPEC = REPO / "desktop" / "build" / "stella-plugin-runner.spec"
DEFAULT_PLUGINS = REPO / "resources" / "default-plugins.json"

DOMAINS = ("bills", "tasks", "calendar", "email", "elearning", "briefing", "automation")
FORBIDDEN_TOP_LEVEL = {"agent", "application", "channel", "app"}


def _plugin_roots():
    roots = [WORKSPACE]
    if SIBLING.is_dir():
        roots.append(SIBLING)
    return roots


def _spec_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _assigned_list(tree: ast.Module, name: str) -> list[str]:
    """String literals assigned (``=``) or appended (``+= [...]``) to a module-level list."""
    values: list[str] = []
    found = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            found = True
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            found = True
        else:
            continue
        if isinstance(node.value, ast.List):
            values.extend(e.value for e in node.value.elts if isinstance(e, ast.Constant))
    assert found, f"{name} not found"
    return values


def _string_call_args(tree: ast.Module, func_name: str) -> list[tuple[str, ...]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == func_name:
            found.append(
                tuple(a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str))
            )
    return found


@pytest.mark.parametrize("root", _plugin_roots(), ids=lambda p: p.parent.name)
@pytest.mark.parametrize("domain", DOMAINS)
def test_default_domain_package_exists(root, domain):
    package = root / domain
    manifest = json.loads((package / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["id"] == f"stella.{domain}"
    entry = manifest["runtime"]["entry"]
    assert (package / entry).is_file()


def test_default_plugins_json_lists_all_seven_domains():
    data = json.loads(DEFAULT_PLUGINS.read_text(encoding="utf-8"))
    ids = {item["pluginId"] for item in data["plugins"]}
    assert ids == {f"stella.{d}" for d in DOMAINS}
    for item in data["plugins"]:
        assert item["catalogRef"] == f"official/{item['pluginId']}"
        assert item["defaultEnabled"] is True


def test_frozen_runner_spec_excludes_app_and_agent():
    excludes = set(_assigned_list(_spec_tree(RUNNER_SPEC), "excludes"))
    assert {"app", "application", "agent", "channel", "plugins", "core.services"} <= excludes
    hidden = _assigned_list(_spec_tree(RUNNER_SPEC), "hiddenimports")
    assert not [name for name in hidden if name.split(".")[0] in FORBIDDEN_TOP_LEVEL]


def test_backend_spec_does_not_bundle_bills_schema_or_blanket_business_packages():
    tree = _spec_tree(BACKEND_SPEC)
    for parts in _string_call_args(tree, "rp"):
        assert not (parts[:2] == ("agent", "bills")), f"bills data still frozen: {parts}"
    collected = [args[0] for args in _string_call_args(tree, "collect_submodules") if args]
    assert "agent.calendar" not in collected
    assert "agent.briefing" not in collected
    # Apple EventKit bridge stays in Core.
    hidden = _assigned_list(tree, "hiddenimports")
    assert "agent.calendar.apple_bridge" in hidden


def test_backend_spec_documents_runner_sibling_and_core_plugins():
    text = BACKEND_SPEC.read_text(encoding="utf-8")
    assert "stella-plugin-runner" in text
    assert "next to" in text.lower() or "NEXT TO" in text
    assert "core.plugins" in text
    assert RUNNER_SPEC.is_file()


def _imports(path: Path) -> list[str]:
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize("root", _plugin_roots(), ids=lambda p: p.parent.name)
def test_plugin_packages_have_no_host_agent_imports(root):
    offenders = []
    for domain in DOMAINS:
        for path in (root / domain).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for name in _imports(path):
                if name.split(".")[0] in FORBIDDEN_TOP_LEVEL:
                    offenders.append(f"{path.relative_to(root)}: {name}")
    assert offenders == []


# -- legacy PluginManager must not become a second writer ------------------------


def test_legacy_plugin_manager_skips_runtime_packages_and_business_names(tmp_path):
    from plugins.plugin_manager import legacy_skip_reason

    package = tmp_path / "anything"
    package.mkdir()
    assert legacy_skip_reason("anything", str(package)) is None
    (package / "plugin.json").write_text("{}", encoding="utf-8")
    assert "Plugin Runtime" in legacy_skip_reason("anything", str(package))
    plain = tmp_path / "bills"
    plain.mkdir()
    for name in ("bills", "Tasks", "stella.calendar", "briefing", "email", "elearning", "automation"):
        assert legacy_skip_reason(name, str(plain)), name
    assert legacy_skip_reason("godcmd", str(plain)) is None


def test_shipped_legacy_plugin_dirs_still_load_by_name():
    from plugins.plugin_manager import legacy_skip_reason

    plugins_dir = REPO / "plugins"
    for entry in plugins_dir.iterdir():
        if entry.is_dir() and (entry / "__init__.py").is_file():
            assert legacy_skip_reason(entry.name, str(entry)) is None, entry.name


# -- public collaboration surfaces prefer the plugin facade ----------------------


def test_public_surfaces_use_plugin_facade_when_enabled(monkeypatch):
    from core.services import calendar_public, todos_public

    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    monkeypatch.setenv("STELLA_CALENDAR_PLUGIN", "1")
    assert type(todos_public.default_service()).__name__ == "TodosPluginFacade"
    assert type(calendar_public.default_service()).__name__ == "CalendarPluginFacade"


def test_calendar_public_surface_refuses_legacy_fallback_when_plugin_off(monkeypatch, tmp_path):
    from core.services import calendar_public

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STELLA_CALENDAR_PLUGIN", raising=False)
    with pytest.raises(RuntimeError, match="stella.calendar"):
        calendar_public.default_service()


def test_tasks_surfaces_refuse_legacy_fallback_when_plugin_off(monkeypatch, tmp_path):
    from application.api import Application, RequestContext
    from core.services import todos_public

    _clear_domain_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="requires the stella.tasks plugin"):
        todos_public.default_service()
    with pytest.raises(RuntimeError, match="requires the stella.tasks plugin"):
        Application.port("todos", RequestContext(user_id="g5-user"))


def test_core_has_no_legacy_todo_service():
    import importlib.util

    import agent.todos

    assert not hasattr(agent.todos, "TodoService")
    assert importlib.util.find_spec("agent.todos.service") is None
    assert not (REPO / "agent/todos/service.py").exists()


def test_briefing_tombstone_check_uses_explicit_public_peer_adapters():
    from tests.briefing_domain import BriefingActions
    calls = []
    class Tomb:
        def __init__(self, label): self.label = label
        def has_source_tombstone(self, keys):
            calls.append((self.label, sorted(keys)))
            return self.label == 'todo'
    actions = BriefingActions.__new__(BriefingActions)
    actions._todos, actions._calendar = Tomb('todo'), Tomb('calendar')
    actions._legacy_keys = lambda db, key: {key}
    assert actions._was_deleted(None, 'k', 'todo') is True
    assert actions._was_deleted(None, 'k', 'event') is False
    assert [label for label, _ in calls] == ['todo', 'calendar']


def test_briefing_domain_requires_public_peer_adapters():
    from tests.briefing_domain import BriefingActions, actions_module
    actions = BriefingActions.__new__(BriefingActions)
    actions._todos = actions._calendar = None
    with pytest.raises(actions_module.AdapterUnavailable):
        actions.require_adapters('test')


# -- desktop bootstrap + Application.port: one writer per domain -----------------

from core.plugins.bootstrap import DOMAIN_ENV, apply_desktop_plugin_defaults  # noqa: E402

PORT_FACADES = {
    "calendar": ("STELLA_CALENDAR_PLUGIN", "CalendarPluginFacade"),
    "todos": ("STELLA_TODOS_PLUGIN", "TodosPluginFacade"),
    "bills": ("STELLA_BILLS_PLUGIN", "BillsPluginFacade"),
    "email": ("STELLA_EMAIL_PLUGIN", "EmailPluginFacade"),
    "elearning": ("STELLA_ELEARNING_PLUGIN", "ElearningPluginFacade"),
    "briefing": ("STELLA_BRIEFING_PLUGIN", "BriefingPluginFacade"),
}


def _clear_domain_env(monkeypatch):
    for env_name in DOMAIN_ENV.values():
        # setenv-then-delenv records the original state, so env written later by
        # apply_desktop_plugin_defaults is undone at teardown (a bare delenv of an
        # unset name registers nothing and would leak flags into later tests).
        monkeypatch.setenv(env_name, "")
        monkeypatch.delenv(env_name)


def test_desktop_bootstrap_activates_every_default_domain(monkeypatch, tmp_path):
    _clear_domain_env(monkeypatch)
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    applied = apply_desktop_plugin_defaults(
        installed_ids=[f"stella.{d}" for d in DOMAINS], intents_path=tmp_path / "none.json"
    )
    assert set(applied) == set(DOMAIN_ENV.values())
    assert set(DOMAIN_ENV) == {f"stella.{d}" for d in DOMAINS}
    import os

    assert all(os.environ[name] == "1" for name in DOMAIN_ENV.values())


def test_desktop_bootstrap_honours_removed_disabled_and_explicit_off(monkeypatch, tmp_path):
    _clear_domain_env(monkeypatch)
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setenv("STELLA_EMAIL_PLUGIN", "0")
    intents = tmp_path / "intents.json"
    intents.write_text(json.dumps({"stella.tasks": "removed", "stella.bills": "disabled"}))
    applied = apply_desktop_plugin_defaults(
        installed_ids=[f"stella.{d}" for d in DOMAINS], intents_path=intents
    )
    import os

    for name in ("STELLA_TODOS_PLUGIN", "STELLA_BILLS_PLUGIN"):
        assert name not in applied and name not in os.environ
    assert os.environ["STELLA_EMAIL_PLUGIN"] == "0" and "STELLA_EMAIL_PLUGIN" not in applied


def test_non_desktop_never_activates_plugin_env(monkeypatch, tmp_path):
    _clear_domain_env(monkeypatch)
    monkeypatch.delenv("STELLA_DESKTOP", raising=False)
    assert apply_desktop_plugin_defaults(installed_ids=list(DOMAIN_ENV), intents_path=None) == {}
    import os

    assert not [n for n in DOMAIN_ENV.values() if n in os.environ]


@pytest.mark.parametrize("domain", sorted(PORT_FACADES))
def test_application_port_uses_facade_after_desktop_activation(monkeypatch, tmp_path, domain):
    from application.api import Application, RequestContext

    _clear_domain_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    apply_desktop_plugin_defaults(
        installed_ids=[f"stella.{d}" for d in DOMAINS], intents_path=tmp_path / "none.json"
    )
    port = Application.port(domain, RequestContext(user_id="g5-user"))
    assert type(port._service).__name__ == PORT_FACADES[domain][1]


def test_application_port_briefing_has_only_plugin_facade(monkeypatch):
    from application import Application
    monkeypatch.setenv('STELLA_BRIEFING_PLUGIN', '1')
    assert type(Application.port('briefing')._service).__name__ == 'BriefingPluginFacade'


@pytest.mark.parametrize("domain", ["email", "elearning"])
def test_plugin_only_domains_refuse_legacy_fallback(monkeypatch, tmp_path, domain):
    from application.api import Application, RequestContext

    _clear_domain_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="requires the stella"):
        Application.port(domain, RequestContext(user_id="g5-user"))


def test_application_scheduler_uses_automation_facade_when_plugin_on(monkeypatch):
    from application.api import Application

    class Store:
        store_path = "/tmp/automation.db"
        agent_id = "agent-1"

        def _current_user(self):
            return "u"

    monkeypatch.setenv("STELLA_AUTOMATION_PLUGIN", "1")
    assert type(Application.scheduler(Store())).__name__ == "AutomationPluginFacade"
    monkeypatch.setenv("STELLA_AUTOMATION_PLUGIN", "0")
    with pytest.raises(RuntimeError, match="requires the stella.automation plugin"):
        Application.scheduler(Store())


# -- Bills: plugin path must not need the legacy schema writer -------------------


def test_bills_facade_db_path_does_not_construct_legacy_store(monkeypatch, tmp_path):
    from core.services import bills_facade

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))

    assert bills_facade._db_path().name == "bills.db"
    assert not bills_facade._db_path().exists()


def test_app_has_no_bills_schema_writer():
    import app

    assert not hasattr(app, "_init_bills_db")
    assert not (Path(app.__file__).parent / "agent/bills/service.py").exists()
    assert not (Path(app.__file__).parent / "agent/bills/schema.sql").exists()


# -- tombstones prefer the plugin facade when enabled ----------------------------


@pytest.mark.parametrize(
    "module_name,env_name,label",
    [("todos_public", "STELLA_TODOS_PLUGIN", "todos"), ("calendar_public", "STELLA_CALENDAR_PLUGIN", "calendar")],
)
def test_public_tombstone_helper_resolves_facade_without_handle(monkeypatch, module_name, env_name, label):
    import importlib

    module = importlib.import_module(f"core.services.{module_name}")
    seen = []

    class Fake:
        def has_source_tombstone(self, keys):
            seen.append(sorted(keys))
            return True

    monkeypatch.setenv(env_name, "1")
    monkeypatch.setattr(module, "default_service", lambda: Fake())
    assert module.source_key_is_tombstoned(["b", "a"]) is True
    assert seen == [["a", "b"]]


def test_core_ships_no_briefing_domain_writer():
    import importlib.util
    for module in ('service', 'store', 'actions', 'outbox'):
        assert importlib.util.find_spec('agent.briefing.' + module) is None


def test_backend_spec_has_no_briefing_domain_sql():
    shipped = {parts[:3] for parts in _string_call_args(_spec_tree(BACKEND_SPEC), 'rp')
               if parts[:2] == ('agent', 'briefing')}
    assert shipped == set()
