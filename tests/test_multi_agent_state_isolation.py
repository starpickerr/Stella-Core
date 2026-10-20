from pathlib import Path
from types import SimpleNamespace

import pytest

from memory_domain.config import MemoryConfig
from agent.memory import clear_conversation_store_cache, get_conversation_store
from common.runtime_identity import identity_scope
from agent.registry import AgentProfile, AgentRegistry, get_agent_registry, set_agent_registry
from agent.scheduler import (
    get_scheduler_service,
    get_task_store,
    init_scheduler,
    reset_scheduler_services,
)


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    from agent.scheduler import SchedulerService

    monkeypatch.setattr(
        SchedulerService, "start", lambda service: setattr(service, "running", True)
    )
    monkeypatch.setattr(
        SchedulerService, "stop", lambda service: setattr(service, "running", False)
    )
    previous = get_agent_registry()
    registry = AgentRegistry(
        [
            AgentProfile("primary", "Primary", str(tmp_path / "primary")),
            AgentProfile("research", "Research", str(tmp_path / "research")),
        ],
        default_agent_id="primary",
    )
    set_agent_registry(registry)
    clear_conversation_store_cache()
    reset_scheduler_services()
    try:
        yield registry
    finally:
        reset_scheduler_services()
        clear_conversation_store_cache()
        set_agent_registry(previous)


@pytest.fixture
def mcp_workspaces(isolated_registry):
    """Give each Agent an mcp.json naming a server only it should ever boot."""
    import json

    from agent.tools.tool_manager import ToolManager

    for profile in isolated_registry.list(include_disabled=False):
        workspace = Path(profile.workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "mcp.json").write_text(
            json.dumps({"mcpServers": {f"{profile.id}-server": {"command": "true"}}})
        )
    ToolManager.reset_instances()
    try:
        yield isolated_registry
    finally:
        ToolManager.reset_instances()


def _message(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _task(task_id, name):
    return {
        "id": task_id,
        "name": name,
        "enabled": False,
        "schedule": {"type": "cron", "cron": "0 9 * * *"},
        "action": {"type": "send_message", "content": name},
    }


def test_conversations_with_same_session_id_use_different_databases(
    isolated_registry,
):
    primary = isolated_registry.get("primary")
    research = isolated_registry.get("research")
    primary_store = get_conversation_store(primary.workspace)
    research_store = get_conversation_store(research.workspace)

    primary_store.append_messages("same-session", [_message("primary")])
    research_store.append_messages("same-session", [_message("research")])

    assert primary_store is not research_store
    assert primary_store.load_messages("same-session")[0]["content"][0]["text"] == "primary"
    assert research_store.load_messages("same-session")[0]["content"][0]["text"] == "research"
    assert Path(primary_store._db_path) == Path(primary.workspace) / "memory/long-term/index.db"
    assert Path(research_store._db_path) == Path(research.workspace) / "memory/long-term/index.db"


def test_memory_config_keeps_each_agent_index_under_its_workspace(
    isolated_registry,
):
    primary = isolated_registry.get("primary")
    research = isolated_registry.get("research")

    primary_db = MemoryConfig(workspace_root=primary.workspace).get_db_path()
    research_db = MemoryConfig(workspace_root=research.workspace).get_db_path()

    assert primary_db != research_db
    assert primary_db == Path(primary.workspace) / "index.db"
    assert research_db == Path(research.workspace) / "index.db"


def test_scheduler_stores_allow_same_task_id_per_agent(isolated_registry):
    class Bridge:
        agent_registry = isolated_registry

    bridge = Bridge()
    for profile in isolated_registry.list(include_disabled=False):
        assert init_scheduler(bridge, profile.workspace, profile.id)

    primary_store = get_task_store(agent_id="primary")
    research_store = get_task_store(agent_id="research")
    primary_store.add_task(_task("daily", "Primary daily"))
    research_store.add_task(_task("daily", "Research daily"))

    assert primary_store is not research_store
    assert primary_store.get_task("daily")["name"] == "Primary daily"
    assert research_store.get_task("daily")["name"] == "Research daily"
    assert Path(primary_store.store_path) == Path(
        isolated_registry.get("primary").workspace
    ) / "scheduler/tasks.json"
    assert Path(research_store.store_path) == Path(
        isolated_registry.get("research").workspace
    ) / "scheduler/tasks.json"
    assert get_scheduler_service(agent_id="primary") is not get_scheduler_service(
        agent_id="research"
    )


def test_each_agent_boots_only_its_own_mcp_servers(mcp_workspaces, monkeypatch):
    """A process-wide ToolManager let the first Agent to start decide which MCP
    servers existed: everyone else inherited its tools, credentials included,
    and their own servers never booted at all."""
    from agent.tools.tool_manager import ToolManager

    booted = []
    monkeypatch.setattr(
        ToolManager,
        "_load_mcp_tools_async",
        lambda self, configs: booted.append(
            sorted(cfg.get("name") for cfg in configs)
        ),
    )
    # The loader normally runs on a daemon thread; run it inline so the
    # assertion does not race it.
    monkeypatch.setattr(
        "agent.tools.tool_manager.threading.Thread",
        lambda target, args=(), **kwargs: SimpleNamespace(
            start=lambda: target(*args)
        ),
    )

    for agent_id in ("primary", "research"):
        with identity_scope(agent_id=agent_id):
            ToolManager()._load_mcp_tools()

    assert booted == [["primary-server"], ["research-server"]]


def test_tool_manager_instance_is_per_workspace(mcp_workspaces):
    from agent.tools.tool_manager import ToolManager

    with identity_scope(agent_id="primary"):
        primary = ToolManager()
    with identity_scope(agent_id="research"):
        research = ToolManager()
    with identity_scope(agent_id="primary"):
        assert ToolManager() is primary

    assert primary is not research
    assert primary._mcp_json_path() != research._mcp_json_path()
    assert primary._mcp_json_path().endswith("primary/mcp.json")
    assert research._mcp_json_path().endswith("research/mcp.json")


def test_mcp_path_stays_put_when_the_ambient_identity_is_gone(mcp_workspaces):
    """The MCP loader and hot-reload run on threads that carry no identity;
    the instance has to remember which workspace it belongs to."""
    from agent.tools.tool_manager import ToolManager

    with identity_scope(agent_id="research"):
        research = ToolManager()

    assert research._mcp_json_path().endswith("research/mcp.json")


def test_bound_memory_ports_do_not_transfer_between_users(isolated_registry):
    from core.services.memory_facade import MemoryPort
    from common.runtime_identity import RuntimeIdentity
    port = MemoryPort(identity=RuntimeIdentity(agent_id='primary', user_id='alice'))
    with identity_scope(agent_id='primary', user_id='bob'):
        with pytest.raises(PermissionError, match='another user'):
            port.read(path='MEMORY.md')


def test_core_paths_follow_routing_without_memory_registration(isolated_registry):
    from common.state_dir import state_root
    for agent_id in ('primary', 'research'):
        with identity_scope(agent_id=agent_id):
            workspace = Path(isolated_registry.get(agent_id).workspace)
            assert state_root() == workspace
            assert get_conversation_store() is get_conversation_store(str(workspace))


def test_bound_memory_port_rejects_a_different_agent(isolated_registry):
    from core.services.memory_facade import MemoryPort
    from common.runtime_identity import RuntimeIdentity
    port = MemoryPort(identity=RuntimeIdentity(agent_id='primary'))
    with identity_scope(agent_id='research'):
        with pytest.raises(PermissionError, match='another Agent'):
            port.read(path='MEMORY.md')


def test_no_argument_conversation_store_preserves_single_agent_default(isolated_registry):
    workspace = isolated_registry.get('primary').workspace
    clear_conversation_store_cache()
    assert get_conversation_store() is get_conversation_store(workspace)
    clear_conversation_store_cache()
