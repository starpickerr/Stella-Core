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


def test_public_surfaces_keep_legacy_service_when_plugin_off(monkeypatch, tmp_path):
    from core.services import calendar_public, todos_public

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STELLA_TODOS_PLUGIN", raising=False)
    monkeypatch.delenv("STELLA_CALENDAR_PLUGIN", raising=False)
    assert type(todos_public.default_service()).__name__ == "TodoService"
    assert type(calendar_public.default_service()).__name__ == "CalendarService"


def test_briefing_tombstone_check_routes_through_public_helpers(monkeypatch):
    from agent.briefing.actions import BriefingActions

    calls = []

    class Tomb:
        def __init__(self, label):
            self.label = label

        def has_source_tombstone(self, keys):
            calls.append((self.label, sorted(keys)))
            return self.label == "todo"

    actions = BriefingActions.__new__(BriefingActions)
    actions._todos, actions._calendar = Tomb("todo"), Tomb("calendar")
    actions._legacy_keys = lambda db, key: {key}
    assert actions._was_deleted(None, "k", "todo") is True
    assert actions._was_deleted(None, "k", "event") is False
    assert [label for label, _ in calls] == ["todo", "calendar"]


def test_briefing_tombstone_uses_facade_without_injected_service(monkeypatch):
    from agent.briefing.actions import BriefingActions
    from core.services import calendar_public, todos_public

    seen = []
    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    monkeypatch.setenv("STELLA_CALENDAR_PLUGIN", "1")

    class Fake:
        def __init__(self, label):
            self.label = label

        def has_source_tombstone(self, keys):
            seen.append(self.label)
            return False

    monkeypatch.setattr(todos_public, "default_service", lambda: Fake("todos-facade"))
    monkeypatch.setattr(calendar_public, "default_service", lambda: Fake("calendar-facade"))
    actions = BriefingActions.__new__(BriefingActions)
    actions._todos = actions._calendar = None
    actions._legacy_keys = lambda db, key: {key}
    actions._was_deleted(None, "k", "todo")
    actions._was_deleted(None, "k", "event")
    assert seen == ["todos-facade", "calendar-facade"]
