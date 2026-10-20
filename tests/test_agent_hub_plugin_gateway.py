"""Agent Hub gateway + built-in Provider adapters (Codex / Cursor / Claude)."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

from core.services import agent_hub_gateway

SIBLING_ROOT = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "agent-hub"
WORKSPACE_ROOT = Path("stella-plugins-workspace/plugins/agent-hub")


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_AGENT_HUB_PLUGIN", "1")
    monkeypatch.setattr('common.state_dir.agent_hub_db', lambda **_: tmp_path / 'hub.db')
    monkeypatch.setattr('common.state_dir.executions_dir', lambda **_: tmp_path / 'executions')
    monkeypatch.setenv("STELLA_AGENT_HUB_PLUGIN_ROOT", str(SIBLING_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    yield
    agent_hub_gateway.shutdown_agent_hub_session()


def _ok(method, **params):
    result = agent_hub_gateway.invoke_agent_hub(method, params, agent_id="agent-a")
    assert result["status"] == "succeeded", result
    return result["value"]


def test_plugin_package_has_no_host_imports():
    offenders = []
    for path in SIBLING_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in {"agent", "common", "channel", "application", "core"}:
                    offenders.append(f"{path}: {name}")
    assert offenders == []


def test_descriptors_match_gateway_table():
    spec = importlib.util.spec_from_file_location(
        "stella_agent_hub_entry_for_test", SIBLING_ROOT / "backend" / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    backend = str((SIBLING_ROOT / "backend").resolve())
    sys.path.insert(0, backend)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(backend)
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]
    descriptor = module.SERVICE_DESCRIPTORS[0]
    assert descriptor["contract"] == "stella.agent-hub@1"
    methods = {m["name"]: m for m in descriptor["methods"]}
    assert set(methods) == set(agent_hub_gateway.AGENT_HUB_METHOD_PARAMS)
    for name, method in methods.items():
        assert tuple(method["inputSchema"]["properties"]) == agent_hub_gateway.AGENT_HUB_METHOD_PARAMS[name]


def test_defaults_overview_and_probe_without_cli(tmp_path):
    created = _ok("ensure_defaults")
    assert {row["providerLocalId"] for row in created} >= {
        "codex-app-server",
        "cursor-acp",
        "claude-code",
    }
    overview = _ok("status_overview")
    assert overview["emptyState"] is True
    assert "不影响其他功能" in overview["message"]
    catalog = _ok("list_catalog")
    assert {c["providerLocalId"] for c in catalog} >= {
        "codex-app-server",
        "codex-cli",
        "cursor-acp",
        "cursor-cli",
        "claude-code",
    }
    providers = _ok("list_providers")
    assert len(providers) >= 5
    probe = _ok("probe_provider", provider_config_id=providers[0]["providerConfigId"])
    assert probe["status"] in {"not_configured", "ready", "blocked"}
    # Probe must not invent credentials.
    blob = str(probe)
    assert "sk-" not in blob
    assert "password" not in blob.lower()


def test_disabled_flag_fail_closed(monkeypatch):
    monkeypatch.setenv("STELLA_AGENT_HUB_PLUGIN", "0")
    agent_hub_gateway.shutdown_agent_hub_session()
    with pytest.raises(RuntimeError, match="disabled"):
        agent_hub_gateway.invoke_agent_hub("status_overview", {}, agent_id="a")


def test_provider_adapters_describe_and_probe_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()
    backend = str((SIBLING_ROOT / "backend").resolve())
    sys.path.insert(0, backend)
    try:
        from domain.providers import get_adapter

        for local_id in ("codex-app-server", "cursor-acp", "claude-code"):
            adapter = get_adapter(local_id)
            desc = adapter.describe()
            assert desc["providerId"].endswith(local_id)
            probe = adapter.probe()
            assert probe["status"] == "not_configured"
            assert probe["installed"] is False
    finally:
        sys.path.remove(backend)
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]


def test_agent_hub_tool_submit_without_provider_returns_execution_id(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()
    from agent.tools.agent_hub.agent_hub_tool import AgentHubTool

    tool = AgentHubTool()
    # Enable plugin + ensure defaults but no ready binary.
    _ok("ensure_defaults")
    result = tool.execute(action="submit", goal="research X", task_kind="research.report")
    assert result.status in {"success", "error"}
    payload = result.result if isinstance(result.result, dict) else {}
    if result.status == "success":
        assert "executionId" in payload
        assert payload["status"] in {"failed", "queued", "running", "outcome_unknown", "succeeded"}


def test_catalog_exposes_agent_and_access_mode():
    catalog = _ok("list_catalog")
    by_id = {row["providerLocalId"]: row for row in catalog}
    assert by_id["codex-app-server"]["agentId"] == "codex"
    assert by_id["codex-app-server"]["accessMode"] == "app-server"
    assert by_id["codex-cli"]["agentId"] == "codex"
    assert by_id["codex-cli"]["accessMode"] == "cli"
    assert by_id["cursor-cli"]["agentId"] == "cursor"
    assert by_id["cursor-cli"]["accessMode"] == "cli"
    assert {row["providerLocalId"] for row in catalog} >= {
        "codex-app-server",
        "codex-cli",
        "cursor-acp",
        "cursor-cli",
        "claude-code",
    }


def test_cursor_cli_forbids_force_flags_and_describes_honestly(tmp_path):
    backend = str((SIBLING_ROOT / "backend").resolve())
    sys.path.insert(0, backend)
    try:
        from domain.providers.cursor_cli import CursorCliProvider

        provider = CursorCliProvider(binary_path=str(tmp_path / "missing-agent"))
        desc = provider.describe()
        assert desc["agentId"] == "cursor"
        assert desc["accessMode"] == "cli"
        assert desc["capabilities"]["approvalBridge"] is False
        # argv builder must never inject force/yolo
        argv = provider._print_argv("/usr/bin/agent", "goal")
        assert "--force" not in argv and "--yolo" not in argv and "-f" not in argv
        assert "-p" in argv
    finally:
        sys.path.remove(backend)
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]


def test_codex_app_server_does_not_silently_fall_back_to_cli(tmp_path, monkeypatch):
    """D24: app-server failures must reject, not pretend to be CLI exec."""
    backend = str((SIBLING_ROOT / "backend").resolve())
    sys.path.insert(0, backend)
    try:
        from domain.providers.codex_app_server import CodexAppServerProvider

        provider = CodexAppServerProvider(binary_path=str(tmp_path / "missing-codex"))
        result = provider.start(
            {
                "executionId": "e1",
                "workspacePath": str(tmp_path),
                "goal": "hi",
                "budget": {"maxWallTime": 5},
            }
        )
        assert result["status"] == "rejected"
        assert "oneshot" not in str(result).lower()
        assert provider.describe()["capabilities"]["reattach"] is False
        assert provider.describe()["agentId"] == "codex"
        assert provider.describe()["accessMode"] == "app-server"
    finally:
        sys.path.remove(backend)
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]


def test_select_provider_by_agent_id(tmp_path, monkeypatch):
    _ok("ensure_defaults")
    providers = _ok("list_providers")
    for row in providers:
        if row["providerLocalId"] != "codex-cli":
            continue
        _ok(
            "upsert_provider",
            provider={
                **row,
                "enabled": True,
                "binaryPath": str(tmp_path / "nope"),
                "lastProbe": {"status": "ready"},
            },
        )
    selected = _ok("select_provider", selector={"agentId": "codex", "accessMode": "cli"})
    assert selected["providerLocalId"] == "codex-cli"
    assert selected["agentId"] == "codex"


def test_apply_user_preferences_syncs_binary_paths(tmp_path, monkeypatch):
    binary = tmp_path / "fake-codex"
    binary.write_text("#!/bin/sh\necho codex 0.0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()

    prefs = {
        "default_provider_local_id": "codex-app-server",
        "codex_binary_path": str(binary),
        "cursor_binary_path": "",
        "claude_binary_path": "",
    }
    monkeypatch.setattr(agent_hub_gateway, "read_user_preferences", lambda **_: prefs)

    synced = agent_hub_gateway.apply_user_preferences()
    assert synced["defaultProviderLocalId"] == "codex-app-server"
    providers = {row["providerLocalId"]: row for row in _ok("list_providers")}
    assert providers["codex-app-server"]["binaryPath"] == str(binary)
    assert providers["codex-app-server"]["enabled"] is True

    selector = agent_hub_gateway.resolve_provider_selector({})
    assert selector == {"providerLocalId": "codex-app-server"}


def test_preferences_do_not_reenable_a_disabled_provider(tmp_path, monkeypatch):
    binary = str(tmp_path / 'codex')
    monkeypatch.setattr(agent_hub_gateway, 'read_user_preferences', lambda **_: {'codex_binary_path': binary})
    agent_hub_gateway.apply_user_preferences()
    row = next(row for row in _ok('list_providers') if row['providerLocalId'] == 'codex-cli')
    _ok('upsert_provider', provider={**row, 'enabled': False})
    agent_hub_gateway.apply_user_preferences()
    assert _ok('get_provider', provider_config_id=row['providerConfigId'])['enabled'] is False


def test_absent_preferences_do_not_erase_provider_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_hub_gateway, 'read_user_preferences', lambda **_: {})
    binary = str(tmp_path / 'codex')
    row = _ok('upsert_provider', provider={'providerLocalId': 'codex-cli', 'enabled': True, 'binaryPath': binary})
    agent_hub_gateway.apply_user_preferences()
    assert _ok('get_provider', provider_config_id=row['providerConfigId'])['binaryPath'] == binary
