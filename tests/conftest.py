# encoding:utf-8
"""Keep the suite out of the developer's real workspace.

Whatever a test loads config for, ``agent_workspace`` ends up pointing at the
directory the person running the suite actually uses, and anything that resolves
a path without pinning one down writes there: the memory files, the scheduler
store and the tmp directory are all reachable that way.

Only that one key is redirected, and only for the session. Loading the config
outright would be worse than the problem: tests would inherit the developer's
model, language and channel settings, and start passing or failing on them.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True, scope="session")
def workspace_out_of_the_way():
    import config as config_module

    with tempfile.TemporaryDirectory(prefix="stella-tests-") as tmp:
        workspace = os.path.join(tmp, "stella")
        real_load = config_module.load_config

        def load_then_redirect():
            real_load()
            config_module.conf()["agent_workspace"] = workspace

        # Applied now for tests that never load, and re-applied after any that
        # do, since loading replaces the value with the real one.
        config_module.conf()["agent_workspace"] = workspace
        config_module.load_config = load_then_redirect

        # Collection imports every test module before this runs, and a module
        # that loads config on import can leave a registry or a store already
        # resolved against the real path. Drop those.
        _forget_resolved_paths()
        # Standalone tool tests bypass Agent startup, which creates Work.
        from common.state_dir import personal_work_dir
        personal_work_dir(base=workspace)
        try:
            yield workspace
        finally:
            config_module.load_config = real_load


def _forget_resolved_paths():
    from agent.memory import clear_conversation_store_cache
    from agent.memory.config import reset_memory_configs
    from agent.registry import set_agent_registry

    set_agent_registry(None)
    reset_memory_configs()
    clear_conversation_store_cache()


@pytest.fixture(autouse=True)
def security_audit_path(monkeypatch):
    """Keep policy checks out of the real Security Center and remove them after each test."""
    with tempfile.TemporaryDirectory(prefix="stella-security-test-") as directory:
        path = Path(directory) / "security-activity.jsonl"
        monkeypatch.setattr("agent.permission.audit._path", lambda: path)
        yield path


@pytest.fixture
def deterministic_briefing_generator(monkeypatch):
    """Run the production generator with scripted tool calls, never a provider."""
    from agent.briefing.generator import AgentBriefingGenerator
    from briefing_fakes import DeterministicBriefingModel

    def generator(**kwargs):
        return AgentBriefingGenerator(**{**kwargs, "model": DeterministicBriefingModel()})

    monkeypatch.setattr("agent.briefing.pipeline.AgentBriefingGenerator", generator)
    return generator


@pytest.fixture
def todos_plugin_env(monkeypatch):
    """Route the Tasks port to the real ``stella.tasks`` worker (workspace mirror)."""
    from core.services import todos_gateway

    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("STELLA_TODOS_PLUGIN", "1")
    monkeypatch.setenv("STELLA_TODOS_PLUGIN_ROOT", str(repo / "stella-plugins-workspace" / "plugins" / "tasks"))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(repo))
    monkeypatch.setenv("STELLA_TODOS_PLUGIN_SCHEDULER_SYNC", "0")
    yield
    todos_gateway.shutdown_todos_session()


@pytest.fixture
def todos_plugin(todos_plugin_env, tmp_path, monkeypatch):
    """Real-worker Tasks facade over ``tmp_path/todos.db``.

    Reminder links are reconciled by the host into a ``TaskStore`` under
    ``tmp_path/scheduler``, exposed as ``facade.scheduler_store``.
    """
    from agent.scheduler.store import TaskStore
    from agent.todos import scheduler_link
    from core.services import todos_facade

    store = TaskStore(str(tmp_path / "scheduler" / "tasks.json"))
    monkeypatch.setattr(todos_facade, "_db_paths", lambda: (tmp_path / "todos.db", tmp_path / "calendar.db"))
    monkeypatch.setattr(scheduler_link, "default_scheduler_store", lambda: store)
    monkeypatch.setenv("STELLA_TODOS_PLUGIN_SCHEDULER_SYNC", "1")
    facade = todos_facade.TodosPluginFacade()
    facade.scheduler_store = store
    return facade


@pytest.fixture(scope="session")
def tasks_domain():
    """The vendored stella.tasks domain package, for seeding legacy rows in Core tests only."""
    import importlib
    import importlib.util

    root = Path(__file__).resolve().parents[1] / "stella-plugins-workspace" / "plugins" / "tasks" / "backend" / "domain"
    name = "stella_tasks_domain_core_seed"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, root / "__init__.py",
                                                      submodule_search_locations=[str(root)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    return importlib.import_module(name + ".service")


@pytest.fixture
def calendar_plugin_env(monkeypatch):
    """Route Calendar to the real workspace worker, without any host fallback."""
    from core.services import calendar_gateway
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('STELLA_CALENDAR_PLUGIN', '1')
    monkeypatch.setenv('STELLA_CALENDAR_PLUGIN_ROOT', str(repo / 'stella-plugins-workspace/plugins/calendar'))
    monkeypatch.setenv('STELLA_REPO_ROOT', str(repo))
    yield
    calendar_gateway.shutdown_calendar_session()


@pytest.fixture
def calendar_plugin(calendar_plugin_env, tmp_path, monkeypatch):
    from core.services import calendar_facade
    monkeypatch.setattr(calendar_facade, '_db_path', lambda: tmp_path / 'calendar.db')
    return calendar_facade.CalendarPluginFacade()


@pytest.fixture
def briefing_plugin_env(monkeypatch):
    from core.services import briefing_gateway
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('STELLA_BRIEFING_PLUGIN', '1')
    monkeypatch.setenv('STELLA_BRIEFING_PLUGIN_ROOT', str(repo / 'stella-plugins-workspace/plugins/briefing'))
    monkeypatch.setenv('STELLA_REPO_ROOT', str(repo))
    yield
    briefing_gateway.shutdown_briefing_session()


@pytest.fixture
def email_plugin_env(monkeypatch, tmp_path):
    from core.services import email_gateway, email_facade
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('STELLA_EMAIL_PLUGIN', '1')
    monkeypatch.setenv('STELLA_EMAIL_PLUGIN_ROOT', str(repo / 'stella-plugins-workspace/plugins/email'))
    monkeypatch.setenv('STELLA_REPO_ROOT', str(repo))
    monkeypatch.setattr(email_facade, '_paths', lambda: (tmp_path / 'email.db', tmp_path / 'mailbox.json'))
    yield
    email_gateway.shutdown_email_session()
