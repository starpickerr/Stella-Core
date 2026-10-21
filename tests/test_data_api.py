"""Authenticated native API over actual isolated Data Service state."""

import json
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from core.data.api import DataController
from core.data.service import DataService, ProviderRegistry
from tests.test_data_service import Provider
from channel.desktop import desktop_channel as desktop


@pytest.fixture
def env(tmp_path, monkeypatch):
    provider = Provider()
    registry = ProviderRegistry()
    registry.register("messages", provider)
    service = DataService(tmp_path / "data.db", registry)
    service.discover()
    controller = DataController(service, consumers={"test": lambda event: None})
    monkeypatch.setattr("core.data.api.current_controller", lambda: controller)
    with (
        patch.object(desktop, "_require_auth") as auth,
        patch.object(desktop.web, "header"),
    ):
        yield controller, service, provider, auth


def call(handler, method="POST", body=None, params=None):
    with (
        patch.object(desktop.web, "data", return_value=json.dumps(body or {}).encode()),
        patch.object(
            desktop.web, "input", return_value=SimpleNamespace(**(params or {}))
        ),
    ):
        return json.loads(getattr(handler(), method)())


def test_snapshot_records_commands_and_strict_configuration(env):
    controller, service, _, auth = env
    snapshot = call(desktop.DataManagementHandler, "GET", params={"refresh": "0"})
    assert snapshot["status"] == "success" and snapshot["sources"][0]["name"] == "Inbox"
    synced = call(
        desktop.DataCommandHandler,
        body={"action": "sync", "source_id": "messages:a", "options": {}},
    )
    assert synced["status"] == "success"
    records = call(
        desktop.DataRecordsHandler,
        "GET",
        params={"source_id": "messages:a", "q": "First", "limit": "10", "offset": "0"},
    )
    assert records["records"][0]["item"]["payload"]["body"] == "content"
    assert "password" not in json.dumps(snapshot)
    rejected = call(
        desktop.DataCommandHandler,
        body={"action": "source", "source_id": "messages:a", "data_dir": "/elsewhere"},
    )
    assert rejected["status"] == "error"
    assert service.list_sources()[0]["config"] == {}
    assert auth.call_count == 4


def test_subscription_delivery_errors_and_retry_are_operable(env):
    controller, service, _, _ = env
    result = controller.command(
        {"action": "subscribe", "source_id": "messages:a", "consumer_id": "test"}
    )
    sub = result["subscription"]
    service.sync("messages:a")

    def unavailable(event):
        raise RuntimeError("consumer offline")

    controller.consumers["test"] = unavailable
    assert (
        controller.command({"action": "dispatch", "subscription_id": sub["id"]})[
            "delivery"
        ]["failed"]
        == 1
    )
    controller.consumers["test"] = lambda event: None
    assert (
        controller.command({"action": "dispatch", "subscription_id": sub["id"]})[
            "delivery"
        ]["delivered"]
        == 1
    )
    assert controller.snapshot()["deliveries"][0]["state"] == "delivered"
    with pytest.raises(ValueError, match="consumer"):
        controller.command(
            {
                "action": "subscribe",
                "source_id": "messages:a",
                "consumer_id": "arbitrary-code",
            }
        )


def test_api_reports_access_denial_and_authentication_is_not_optional(env):
    _, service, provider, auth = env
    service.sync("messages:a")
    provider.allowed = False
    denied = call(
        desktop.DataRecordsHandler,
        "GET",
        params={"source_id": "messages:a", "q": "", "limit": "50", "offset": "0"},
    )
    assert denied["status"] == "error" and "revoked" in denied["message"]
    assert "content" not in json.dumps(denied)
    auth.side_effect = PermissionError("not authenticated")
    for handler, method in [
        (desktop.DataManagementHandler, "GET"),
        (desktop.DataRecordsHandler, "GET"),
        (desktop.DataCommandHandler, "POST"),
    ]:
        with pytest.raises(PermissionError, match="not authenticated"):
            call(handler, method)


def test_cleanup_refuses_symlink_cache_root(tmp_path):
    from core.data.storage import _clear_directory

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("preserve")
    root = tmp_path / "cache"
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _clear_directory(root)
    assert (outside / "keep").read_text() == "preserve"


def test_command_rejects_non_string_action(env):
    controller, *_ = env
    with pytest.raises(ValueError):
        controller.command({"action": ["sync"]})


def test_security_data_access_view_references_sources_without_storage_controls(
    env, monkeypatch
):
    _, service, *_ = env
    from core.data import runtime
    from agent.permission.privacy import data_access_inventory

    monkeypatch.setattr(runtime, "current_service", lambda: service)
    result = data_access_inventory([])
    assert result["resources"][0]["id"] == "messages:a"
    assert "categories" not in result
    assert "config" not in result["resources"][0]


def test_managed_mcp_connections_have_one_canonical_security_entry(env, monkeypatch):
    from agent.tools.tool_manager import ToolManager
    from agent.permission.center import connections

    manager = ToolManager()
    monkeypatch.setattr(
        manager,
        "mcp_catalog",
        lambda: [
            {
                "name": "email",
                "enabled": True,
                "state": "ready",
                "tools": [],
                "transport": "stdio",
            }
        ],
    )
    monkeypatch.setattr("core.services.email_gateway.email_mcp_enabled", lambda: False)
    rows = connections(
        {
            "connections": {
                "email": {"allowed": False, "scopes": []},
                "mcp:email": {"allowed": True, "scopes": []},
            }
        }
    )
    assert len([row for row in rows if row["id"] in {"email", "mcp:email"}]) == 1
    assert next(row for row in rows if row["id"] == "mcp:email")["allowed"] is False


def test_explicit_canonical_policy_edit_replaces_the_legacy_alias(env, monkeypatch):
    from config import conf

    monkeypatch.setitem(
        conf(),
        "security_policy",
        {
            "preset": "workspace-write",
            "rules": {},
            "connections": {"email": {"allowed": False, "scopes": []}},
        },
    )
    monkeypatch.setattr(
        "agent.permission.center.connections", lambda: [{"id": "mcp:email"}]
    )
    response = call(
        desktop.SecurityConnectionsHandler,
        body={"id": "mcp:email", "allowed": True, "scopes": ["read"]},
    )
    assert response["status"] == "success"
    assert conf()["security_policy"]["connections"]["mcp:email"]["allowed"] is True
    assert "email" not in conf()["security_policy"]["connections"]


def test_disjoint_legacy_scopes_never_display_as_unrestricted(env, monkeypatch):
    from agent.tools.tool_manager import ToolManager
    from agent.permission.center import connections

    monkeypatch.setattr(
        ToolManager(),
        "mcp_catalog",
        lambda: [{"name": "email", "enabled": True, "state": "ready"}],
    )
    row = next(
        row
        for row in connections(
            {
                "connections": {
                    "email": {"allowed": True, "scopes": ["read"]},
                    "mcp:email": {"allowed": True, "scopes": ["write"]},
                }
            }
        )
        if row["id"] == "mcp:email"
    )
    assert row["allowed"] is False


def test_native_briefing_dispatch_checks_the_consumer_grant(env, monkeypatch):
    from core.plugins.authz import PluginAuthorizationStore
    from core.plugins.caller import current_consumer_plugin
    from core.mcp.authorization import check

    controller, service, provider, _ = env
    sub = service.subscribe("messages:a", "briefing")
    service.sync("messages:a")
    authz = PluginAuthorizationStore()
    authz.issue(
        grant_ref="email-default-grant",
        plugin_id="stella.email",
        user_id="local-default",
        capabilities=[],
        purposes=["read"],
    )
    for consumer in ["stella.email", "stella.briefing"]:
        authz.issue_scoped(
            grant_ref=consumer,
            parent_ref="email-default-grant",
            plugin_id="stella.email",
            user_id="local-default",
            consumer_plugin_id=consumer,
            capability="email.fetch",
            methods=["fetch_messages"],
            resources=[{"kind": "user", "id": "local-default"}],
            purpose="interactive",
        )
    authz.revoke("stella.briefing")
    monkeypatch.setattr("core.mcp.authorization.DEFAULT_AUTHZ", authz)

    def authorize(source, operation):
        if operation == "deliver":
            check(
                "email",
                "fetch_messages",
                {},
                "local-default",
                lambda *_: {"source_account_id": "folder-a"},
            )

    provider.authorize = authorize
    received = []

    def handler(self, item):
        received.append(current_consumer_plugin())

    monkeypatch.setattr(
        "core.services.briefing_facade.BriefingPluginFacade.upsert_source_item",
        handler,
        raising=False,
    )
    controller = DataController(service)
    with pytest.raises(PermissionError, match="scoped grant denied"):
        controller.command({"action": "dispatch", "subscription_id": sub["id"]})
    assert received == []
    authz.update_owned(
        "stella.briefing", user_id="local-default", revision=2, revoked=False
    )
    assert (
        controller.command({"action": "dispatch", "subscription_id": sub["id"]})[
            "delivery"
        ]["delivered"]
        == 1
    )
    assert received == ["stella.briefing"]
    from core.plugins.caller import consumer_plugin_scope

    with (
        consumer_plugin_scope("stella.other"),
        pytest.raises(PermissionError, match="cannot be replaced"),
    ):
        controller.command({"action": "dispatch", "subscription_id": sub["id"]})
