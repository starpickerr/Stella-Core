"""User intent persists independently of availability and execution authorization."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest

from agent.tools.capability_settings import CapabilitySettings


def test_preferences_default_without_creating_files_and_survive_recreation(tmp_path):
    first = CapabilitySettings(str(tmp_path / "workspace"), user_id="alice")
    assert first.enabled("tool", "read")
    assert first.enabled("mcp", "Documents")
    assert not first.path.exists()
    first.set_enabled("tool", "read", False)
    assert not CapabilitySettings(str(tmp_path / "workspace"), user_id="alice").enabled(
        "tool", "read"
    )
    first.set_enabled("tool", "read", True)
    assert CapabilitySettings(str(tmp_path / "workspace"), user_id="alice").enabled(
        "tool", "read"
    )


def test_preferences_isolate_users_workspaces_and_concurrent_updates(tmp_path):
    a = CapabilitySettings(str(tmp_path / "a"), user_id="alice")
    b = CapabilitySettings(str(tmp_path / "b"), user_id="alice")
    other = CapabilitySettings(str(tmp_path / "a"), user_id="bob")
    with ThreadPoolExecutor(4) as pool:
        list(
            pool.map(
                lambda name: a.set_enabled("tool", name, False),
                ["read", "write", "bash", "edit"],
            )
        )
    assert all(
        not a.enabled("tool", name) for name in ["read", "write", "bash", "edit"]
    )
    assert b.enabled("tool", "read") and other.enabled("tool", "read")
    assert not a.enabled("mcp", "Documents", default=False)


@pytest.mark.parametrize(
    "kind,name,value",
    [
        ("tool", "read", "false"),
        ("mcp", "Documents", 0),
        ("other", "read", False),
        ("tool", "../read", False),
        ("mcp", "bad\x00name", False),
    ],
)
def test_preferences_reject_invalid_input_without_writes(tmp_path, kind, name, value):
    store = CapabilitySettings(str(tmp_path), user_id="alice")
    with pytest.raises(ValueError):
        store.set_enabled(kind, name, value)
    assert not store.path.exists()


def test_cached_tool_refuses_after_disable_even_inside_existing_invocation(
    tmp_path, monkeypatch
):
    from agent.tools.base_tool import BaseTool, ToolResult, is_tool_available
    from agent.runtime.tool_invocation import invocation_scope, permission_denial

    calls = []

    class Read(BaseTool):
        name = "read"

        def execute(self, args):
            calls.append(args)
            return ToolResult.success("read")

    tool = Read()
    tool._capability_settings = CapabilitySettings(str(tmp_path), user_id="alice")
    tool._capability_settings.set_enabled("tool", "read", False)
    assert not is_tool_available(tool)
    assert "disabled" in permission_denial("read", {}, tool=tool).lower()
    with invocation_scope("already-authorized"):
        assert tool.execute_tool({}).status == "error"
        assert calls == []
        tool._capability_settings.set_enabled("tool", "read", True)
        assert tool.execute_tool({}).status == "success"
        assert calls == [{}]


def test_bound_tool_cannot_read_another_users_setting(tmp_path):
    from common.runtime_identity import identity_scope
    from agent.tools.capability_settings import tool_enabled

    tool = SimpleNamespace(
        name="read",
        _capability_settings=CapabilitySettings(str(tmp_path), user_id="alice"),
    )
    with identity_scope(user_id="bob"):
        with pytest.raises(PermissionError):
            tool_enabled("read", tool=tool)


def _manager(tmp_path, monkeypatch, *, label="workspace"):
    from agent.tools.tool_manager import ToolManager
    from common.runtime_identity import RuntimeIdentity

    manager = object.__new__(ToolManager)
    manager.__init__()
    manager.workspace_root = str(tmp_path / label)
    manager.identity = RuntimeIdentity(user_id="alice")
    manager.capability_settings = CapabilitySettings(
        manager.workspace_root, user_id="alice"
    )
    configs = [{"name": "Documents", "type": "stdio", "command": "not-executed"}]
    monkeypatch.setattr(manager, "_load_mcp_configs", lambda: configs)
    return manager


def _wait(predicate):
    import time

    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, "MCP lifecycle did not settle"
        time.sleep(0.01)


@pytest.fixture
def fake_mcp(monkeypatch):
    from agent.tools.mcp import mcp_client

    clients = []

    class Client:
        def __init__(self, cfg):
            self.name = cfg["name"]
            self.closed = False
            self.calls = []
            clients.append(self)

        def initialize(self):
            return True

        def list_tools(self):
            return [{"name": "echo", "description": "Echo", "inputSchema": {}}]

        def call_tool(self, name, args, **kwargs):
            self.calls.append(args)
            return "echo"

        def shutdown(self):
            self.closed = True

    monkeypatch.setattr(mcp_client, "McpClient", Client)
    return clients, Client


def test_mcp_disable_persists_closes_client_and_reenable_refreshes_cached_agent(
    tmp_path, monkeypatch, fake_mcp
):
    clients, _ = fake_mcp
    manager = _manager(tmp_path, monkeypatch)
    manager.set_mcp_enabled("Documents", False)
    manager._load_mcp_tools()
    assert clients == []
    assert manager.mcp_catalog()[0]["enabled"] is False
    assert manager.mcp_catalog()[0]["state"] == "disabled"
    manager = _manager(tmp_path, monkeypatch)
    manager._load_mcp_tools()
    assert clients == []
    manager.set_mcp_enabled("Documents", True)
    _wait(lambda: manager.list_mcp_status().get("Documents") == "ready")
    cached = next(iter(manager._mcp_tool_instances.values()))
    assert cached.execute({}).status == "success"
    manager.set_mcp_enabled("Documents", False)
    assert clients[0].closed
    assert manager._mcp_tool_instances == {}
    assert cached.execute({}).status == "error"
    manager.set_mcp_enabled("Documents", True)
    _wait(lambda: manager.list_mcp_status().get("Documents") == "ready")
    assert cached.execute({}).status == "error", (
        "re-enabling cannot revive a revoked generation"
    )
    agent = SimpleNamespace(tools={cached.name: cached})
    manager.sync_mcp_into_agent(agent)
    assert agent.tools[cached.name].client is clients[-1]
    assert agent.tools[cached.name].execute({}).status == "success"
    manager.shutdown_mcp()


def test_mcp_late_loader_cannot_replace_new_generation(tmp_path, monkeypatch, fake_mcp):
    import threading

    clients, Client = fake_mcp
    entered = threading.Event()
    release = threading.Event()

    def initialize(self):
        if self is clients[0]:
            entered.set()
            release.wait(3)
        return True

    monkeypatch.setattr(Client, "initialize", initialize)
    manager = _manager(tmp_path, monkeypatch)
    manager._load_mcp_tools()
    assert entered.wait(2)
    manager.set_mcp_enabled("Documents", False)
    assert clients[0].closed, "disabling must close an initializing connection"
    manager.set_mcp_enabled("Documents", True)
    _wait(lambda: manager.list_mcp_status().get("Documents") == "ready")
    try:
        newest = manager._mcp_registry.get("Documents")
        release.set()
        _wait(lambda: clients[0].closed)
        assert manager._mcp_registry.get("Documents") is newest
        assert all(
            tool.client is newest for tool in manager._mcp_tool_instances.values()
        )
    finally:
        release.set()
        manager.shutdown_mcp()


def test_mcp_same_name_uses_private_registry_per_workspace(
    tmp_path, monkeypatch, fake_mcp
):
    a = _manager(tmp_path, monkeypatch, label="a")
    b = _manager(tmp_path, monkeypatch, label="b")
    a.set_mcp_enabled("Documents", True)
    b.set_mcp_enabled("Documents", True)
    _wait(
        lambda: a.list_mcp_status().get("Documents") == "ready"
        and b.list_mcp_status().get("Documents") == "ready"
    )
    try:
        assert a._mcp_registry is not b._mcp_registry
        b_client = b._mcp_registry.get("Documents")
        a.set_mcp_enabled("Documents", False)
        assert not b_client.closed
        assert b._mcp_registry.get("Documents") is b_client
    finally:
        a.shutdown_mcp()
        b.shutdown_mcp()


def test_toggle_apis_require_auth_and_reject_forged_or_invalid_payloads(
    tmp_path, monkeypatch
):
    from channel.desktop import desktop_channel as web

    def deny():
        raise PermissionError("Authentication required")

    monkeypatch.setattr(web, "_require_auth", deny)
    for handler in (web.ToolsHandler, web.McpCatalogHandler):
        with pytest.raises(PermissionError):
            handler().POST()
    monkeypatch.setattr(web, "_require_auth", lambda: None)
    monkeypatch.setattr(web.web, "header", lambda *args, **kw: None)
    import json

    for handler, body in [
        (web.ToolsHandler, {"id": "unknown", "enabled": False}),
        (web.ToolsHandler, {"id": "read", "enabled": "false"}),
        (web.ToolsHandler, {"id": "read", "enabled": False, "userId": "bob"}),
        (web.McpCatalogHandler, {"name": "unknown", "enabled": False}),
        (web.McpCatalogHandler, {"name": "Documents", "enabled": 1}),
    ]:
        monkeypatch.setattr(web.web, "data", lambda: json.dumps(body).encode())
        assert json.loads(handler().POST())["status"] == "error"


def test_closed_mcp_client_cannot_reinitialize(monkeypatch):
    from agent.tools.mcp.mcp_client import McpClient

    client = McpClient({"name": "closed", "type": "stdio", "command": "never-run"})
    attempts = []
    monkeypatch.setattr(client, "_init_stdio", lambda: attempts.append(True) or True)
    client.shutdown()
    assert client.initialize() is False
    assert attempts == []


def test_mcp_disable_terminates_a_real_process_during_initialize(tmp_path, monkeypatch):
    import sys

    marker = tmp_path / "initializing"
    script = tmp_path / "slow_mcp.py"
    script.write_text(
        "import sys,time\nfrom pathlib import Path\nfor line in sys.stdin:\n Path(sys.argv[1]).touch()\n time.sleep(30)\n"
    )
    manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(
        manager,
        "_load_mcp_configs",
        lambda: [
            {
                "name": "Documents",
                "type": "stdio",
                "command": sys.executable,
                "args": [str(script), str(marker)],
            }
        ],
    )
    manager.set_mcp_enabled("Documents", True)
    _wait(marker.exists)
    with manager._mcp_lock:
        client = next(iter(manager._mcp_pending_clients.values()))
        process = client._proc
    manager.set_mcp_enabled("Documents", False)
    _wait(lambda: process.poll() is not None)
    assert manager._mcp_tool_instances == {}
    assert manager.mcp_catalog()[0]["state"] == "disabled"


def test_toggle_http_persists_and_catalog_reads_never_start_other_servers(
    tmp_path, monkeypatch, fake_mcp
):
    import json
    from common.runtime_identity import identity_scope
    from channel.desktop import desktop_channel as web

    manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "common.state_dir.real_state_root", lambda identity=None: manager.workspace_root
    )
    monkeypatch.setattr("agent.tools.tool_manager.ToolManager", lambda: manager)
    monkeypatch.setattr(web, "_require_auth", lambda: None)
    monkeypatch.setattr(web.web, "header", lambda *args, **kw: None)
    with identity_scope(user_id="alice"):
        for handler, body in [
            (web.ToolsHandler, {"id": "read", "enabled": False}),
            (web.McpCatalogHandler, {"name": "Documents", "enabled": False}),
        ]:
            monkeypatch.setattr(web.web, "data", lambda: json.dumps(body).encode())
            assert json.loads(handler().POST())["status"] == "success"
        tools = json.loads(web.ToolsHandler().GET())["tools"]
        assert next(row for row in tools if row["id"] == "read")["enabled"] is False
        assert (
            json.loads(web.McpCatalogHandler().GET())["servers"][0]["enabled"] is False
        )
        assert fake_mcp[0] == []


def test_mcp_config_changed_before_enable_replaces_and_closes_old_client(
    tmp_path, monkeypatch, fake_mcp
):
    clients, _ = fake_mcp
    manager = _manager(tmp_path, monkeypatch)
    manager.set_mcp_enabled("Documents", True)
    _wait(lambda: manager.list_mcp_status().get("Documents") == "ready")
    monkeypatch.setattr(
        manager,
        "_load_mcp_configs",
        lambda: [{"name": "Documents", "type": "stdio", "command": "changed-command"}],
    )
    try:
        manager.set_mcp_enabled("Documents", True)
        _wait(
            lambda: len(clients) == 2
            and manager.list_mcp_status().get("Documents") == "ready"
        )
        assert clients[0].closed
        assert manager._mcp_registry.get("Documents") is clients[1]
    finally:
        manager.shutdown_mcp()


def test_scheduled_tool_rechecks_enablement_after_preparation(
    tmp_path, monkeypatch, registered_agent
):
    from agent.scheduler import integration
    from agent.tools.base_tool import BaseTool, ToolResult
    from agent.runtime.run_record import RunRecord

    profile = registered_agent("alpha")
    from agent.registry import get_agent_registry

    get_agent_registry().set_default("alpha")
    store = CapabilitySettings(profile.workspace)
    calls = []

    class Probe(BaseTool):
        name = "bash"

        def set_cwd(self, cwd):
            store.set_enabled("tool", self.name, False)

        def execute(self, args):
            calls.append(args)
            return ToolResult.success("ran")

    tool = Probe()
    tool._capability_settings = store
    monkeypatch.setattr(
        "agent.tools.tool_manager.ToolManager",
        lambda: SimpleNamespace(create_tool=lambda _: tool),
    )
    monkeypatch.setattr(
        "agent.runtime.tool_invocation.execution_workspace",
        lambda *args, **kwargs: (str(tmp_path), [str(tmp_path)]),
    )
    monkeypatch.setattr(
        "agent.runtime.run_record.RunRecord", lambda: RunRecord(tmp_path / "runs.db")
    )
    monkeypatch.setattr(
        integration, "_resolve_working_dir", lambda **kwargs: str(tmp_path)
    )
    result = integration._run_scheduled_tool(
        {
            "id": "probe",
            "run_permission_mode": "full-access",
            "action": {"silent": True},
        },
        "bash",
        {},
        "alpha",
        None,
        None,
    )
    assert result.status == "failed" and "disabled" in result.error.lower()
    assert calls == []


@pytest.mark.parametrize("wrapper", ["workspace", "memory"])
def test_evolution_wrappers_recheck_disabled_inner_tools(tmp_path, wrapper):
    from agent.evolution.executor import _WorkspaceWriteGuard, _PluginMemoryWriteGuard
    from agent.tools.base_tool import BaseTool, ToolResult
    from agent.runtime.tool_invocation import invocation_scope

    calls = []

    class Probe(BaseTool):
        name = "write" if wrapper == "workspace" else "memory_write"
        description = "test"
        params = {}

        def _resolve_path(self, path):
            return str(tmp_path / path)

        def execute(self, args):
            calls.append(args)
            return ToolResult.success("ran")

    tool = Probe()
    tool._capability_settings = CapabilitySettings(str(tmp_path))
    tool._capability_settings.set_enabled("tool", tool.name, False)
    if wrapper == "workspace":
        guarded = _WorkspaceWriteGuard(
            tool, str(tmp_path), set(), SimpleNamespace(record=lambda path: None)
        )
    else:
        guarded = _PluginMemoryWriteGuard(tool, {"snapshotId": "trusted"})
    with invocation_scope("already-authorized"):
        result = guarded.execute_tool({"path": "report.txt"})
    assert result.status == "error" and "disabled" in str(result.result).lower()
    assert calls == []


@pytest.mark.parametrize("stale", [False, True])
def test_oauth_callback_reloads_only_originating_live_generation(
    tmp_path, monkeypatch, stale
):
    from agent.tools.mcp import mcp_client, mcp_oauth
    from channel.desktop import desktop_channel as web

    monkeypatch.setenv("STELLA_HEADLESS", "1")
    monkeypatch.setattr(mcp_oauth, "_PENDING", {})

    def registered(handler, *args):
        handler.metadata = {"authorization_endpoint": "https://auth.invalid/authorize"}
        handler.client_id = "test-client"
        return True

    monkeypatch.setattr(mcp_oauth.OAuthHandler, "ensure_registered", registered)
    monkeypatch.setattr(
        mcp_oauth.OAuthHandler, "finish_authorization", lambda self, code: True
    )
    monkeypatch.setattr(mcp_client.McpClient, "_url_allowed", lambda self, url: True)
    monkeypatch.setattr(mcp_client.McpClient, "_maybe_load_oauth", lambda self: None)
    monkeypatch.setattr(
        mcp_client.McpClient, "_handshake", lambda self: self._begin_oauth() or False
    )
    a = _manager(tmp_path, monkeypatch, label="a")
    b = _manager(tmp_path, monkeypatch, label="b")
    for manager in (a, b):
        monkeypatch.setattr(
            manager,
            "_load_mcp_configs",
            lambda: [
                {
                    "name": "Documents",
                    "type": "streamable-http",
                    "url": "https://mcp.invalid",
                }
            ],
        )
    try:
        a.set_mcp_enabled("Documents", True)
        _wait(lambda: a.list_mcp_status().get("Documents") == "needs_auth")
        state = next(iter(mcp_oauth._PENDING))
        b.set_mcp_enabled("Documents", True)
        _wait(lambda: b.list_mcp_status().get("Documents") == "needs_auth")
        if stale:
            a.set_mcp_enabled("Documents", False)
            a.set_mcp_enabled("Documents", True)
            _wait(lambda: a.list_mcp_status().get("Documents") == "needs_auth")
        before_a = a._mcp_generations["Documents"]
        before_b = b._mcp_generations["Documents"]
        monkeypatch.setattr(web.web, "header", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            web.web,
            "input",
            lambda **kwargs: SimpleNamespace(
                error="", error_description="", code="test-code", state=state
            ),
        )
        assert "授权成功" in web.McpOAuthCallbackHandler().GET()
        assert b._mcp_generations["Documents"] == before_b
        if stale:
            assert a._mcp_generations["Documents"] == before_a
        else:
            assert a._mcp_generations["Documents"] > before_a
    finally:
        a.shutdown_mcp()
        b.shutdown_mcp()


@pytest.mark.parametrize(
    "phase", ["http-url", "http-oauth", "sse-url", "sse-endpoint", "http-bearer"]
)
def test_remote_mcp_disable_during_preparation_never_dispatches(monkeypatch, phase):
    import threading
    from agent.tools.mcp.mcp_client import McpClient

    client = McpClient(
        {
            "name": "remote",
            "type": "sse" if phase.startswith("sse") else "streamable-http",
            "url": "https://mcp.invalid",
        }
    )
    entered, release = threading.Event(), threading.Event()
    requests, results = [], []

    def pause(value):
        entered.set()
        assert release.wait(3)
        return value

    class Response:
        headers = {"Content-Type": "application/json"}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"result":{}}'

        def close(self):
            pass

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, **kwargs: requests.append(req.get_method()) or Response(),
    )
    monkeypatch.setattr(client, "_url_allowed", lambda url: True)
    monkeypatch.setattr(client, "_maybe_load_oauth", lambda: None)
    if phase.endswith("-url"):
        monkeypatch.setattr(client, "_url_allowed", lambda url: pause(True))
    elif phase == "http-oauth":
        monkeypatch.setattr(client, "_maybe_load_oauth", lambda: pause(None))
    elif phase == "sse-endpoint":
        monkeypatch.setattr(
            client, "_sse_discover_endpoint", lambda: pause("https://mcp.invalid/post")
        )
    else:
        client._http_url = "https://mcp.invalid"
        client._initialized = True
        monkeypatch.setattr(client, "_current_bearer", lambda: pause("test-token"))

    def initialize():
        try:
            result = (
                client._streamable_http_post({"id": 1, "method": "tools/call"}, True)
                if phase == "http-bearer"
                else client.initialize()
            )
            results.append(result)
        except (RuntimeError, IOError):
            results.append(False)

    worker = threading.Thread(target=initialize)
    worker.start()
    try:
        assert entered.wait(3)
        client.shutdown()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert requests == []
    assert results == [False] and client._initialized is False


def test_remote_mcp_closes_session_assigned_after_shutdown(monkeypatch):
    import threading
    from agent.tools.mcp.mcp_client import McpClient

    client = McpClient(
        {"name": "remote", "type": "streamable-http", "url": "https://mcp.invalid"}
    )
    entered, release = threading.Event(), threading.Event()
    requests, results = [], []
    closed = []

    class Response:
        headers = {"Content-Type": "application/json", "Mcp-Session-Id": "late-session"}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def read(self):
            return b'{"result":{}}'

        def close(self):
            closed.append(True)

    def remote(req, **kwargs):
        requests.append((req.get_method(), req.get_header("Mcp-session-id")))
        if req.get_method() == "POST":
            entered.set()
            assert release.wait(3)
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", remote)
    monkeypatch.setattr(client, "_url_allowed", lambda url: True)
    monkeypatch.setattr(client, "_maybe_load_oauth", lambda: None)
    worker = threading.Thread(target=lambda: results.append(client.initialize()))
    worker.start()
    try:
        assert entered.wait(3)
        client.shutdown()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert results == [False]
    assert requests == [("POST", None), ("DELETE", "late-session")]
    assert client._http_session_id is None and client._initialized is False
    assert closed


def test_post_process_tools_cannot_bypass_disabled_state(tmp_path):
    from agent.protocol.agent import Agent
    from agent.tools.base_tool import BaseTool, ToolResult, ToolStage

    calls, records = [], []

    class Probe(BaseTool):
        name = "read"
        stage = ToolStage.POST_PROCESS

        def execute(self, args):
            calls.append(args)
            return ToolResult.success("ran")

    tool = Probe()
    tool._capability_settings = CapabilitySettings(str(tmp_path))
    tool._capability_settings.set_enabled("tool", tool.name, False)
    agent = object.__new__(Agent)
    agent.tools = [tool]
    agent.output = lambda *args, **kwargs: None
    agent.capture_tool_use = lambda **kwargs: records.append(kwargs)
    agent._execute_post_process_tools()
    assert calls == []
    assert (
        records[0]["status"] == "error"
        and "disabled" in records[0]["error_message"].lower()
    )


def test_stdio_drainers_keep_process_streams_when_shutdown_interleaves(monkeypatch):
    import io
    from agent.tools.mcp import mcp_client

    client = mcp_client.McpClient({"name": "closing", "command": "not-run"})
    process = SimpleNamespace(
        pid=1,
        stdin=io.StringIO(),
        stdout=io.StringIO("reply\n"),
        stderr=io.StringIO(),
        terminate=lambda: None,
        wait=lambda **kwargs: None,
    )
    monkeypatch.setattr(mcp_client.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(client, "_command_allowed", lambda command: True)
    errors = []

    class ImmediateThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args

        def start(self):
            client.shutdown()
            try:
                self.target(*self.args)
            except Exception as exc:
                errors.append(exc)

    monkeypatch.setattr(mcp_client.threading, "Thread", ImmediateThread)
    assert client.initialize() is False
    assert errors == []
    assert client._proc is None and client._closed
