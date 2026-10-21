"""An independent MCP supplies generic data used by separate consumers."""

import pytest
from core.data.service import DataService, ProviderRegistry
from core.data.providers import McpProvider, EMAIL_MAPPING, DataSource


@pytest.fixture
def integration(tmp_path, monkeypatch):
    from config import conf
    from core.services.email_facade import EmailMcpFacade
    from agent.tools.tool_manager import ToolManager
    from tests.test_managed_mcp_domains import fake_config

    monkeypatch.setenv("STELLA_MANAGED_MCP", "1")
    monkeypatch.setitem(conf(), "agent_permission_mode", "full-access")
    monkeypatch.setitem(
        conf(),
        "security_policy",
        {"preset": "full-access", "rules": {}, "connections": {}},
    )
    manager = ToolManager()
    config = {
        **fake_config("email", tmp_path / "email"),
        "agentTools": ["list_accounts", "list_sources", "fetch_messages"],
        "settingsUrl": "/email",
    }
    monkeypatch.setattr(manager, "_load_mcp_configs", lambda: [config])
    was_enabled = manager._mcp_enabled(config)
    manager.set_mcp_enabled("email", True)
    facade = EmailMcpFacade()
    account = facade.save_account(
        {"host": "imap.example.test", "user": "test@example.test", "password": "fake"}
    )
    registry = ProviderRegistry()
    registry.register("email", McpProvider("email", EMAIL_MAPPING, manager))
    service = DataService(tmp_path / "data.db", registry)
    service.discover()
    try:
        yield service, manager, account
    finally:
        manager.set_mcp_enabled("email", was_enabled)
        manager._teardown_mcp_server("email")


def test_mcp_data_collection_and_generic_briefing_consumer(integration):
    service, _, _ = integration
    source = service.list_sources()[0]
    adapter = DataSource(service, source)
    result = adapter.fetch(
        {"since": "2026-09-08T00:00:00Z", "until": "2026-09-10T00:00:00Z"}
    )
    assert result.items and result.items[0].source == "email"
    assert result.items[0].payload["body"]
    # An unchanged second fetch still gives the consumer the cached window.
    repeated = adapter.fetch(
        {"since": "2026-09-08T00:00:00Z", "until": "2026-09-10T00:00:00Z"}
    )
    assert [item.source_id for item in repeated.items] == [
        item.source_id for item in result.items
    ]
    assert len(service.query(source["id"])["records"]) == len(result.items)
    assert not any("password" in str(row) for row in service.list_sources())


def test_runtime_revocation_blocks_cached_body_and_mcp_switch_is_authoritative(
    integration, monkeypatch
):
    service, manager, _ = integration
    source = service.list_sources()[0]
    service.sync(source["id"], {"since": "2026-09-08T00:00:00Z"})
    assert service.query(source["id"])["records"]
    from config import conf

    monkeypatch.setitem(
        conf(),
        "security_policy",
        {
            "preset": "full-access",
            "rules": {},
            "connections": {"mcp:email": {"allowed": False}},
        },
    )
    with pytest.raises(PermissionError, match="revoked"):
        service.query(source["id"])
    monkeypatch.setitem(
        conf(),
        "security_policy",
        {"preset": "full-access", "rules": {}, "connections": {}},
    )
    manager.set_mcp_enabled("email", False)
    with pytest.raises(PermissionError, match="disabled"):
        service.query(source["id"])


def test_second_consumer_receives_same_mcp_data_without_mail_adapter(integration):
    service, _, _ = integration
    source = service.list_sources()[0]
    sub = service.subscribe(source["id"], "knowledge-test")
    service.sync(source["id"], {"since": "2026-09-08T00:00:00Z"})
    entries = []
    assert service.dispatch(sub["id"], entries.append)["delivered"] > 0
    assert entries[0]["record"]["source"] == "email"


def test_production_briefing_source_directory_consumes_data_service(
    integration, monkeypatch, tmp_path
):
    service, _, _ = integration
    from core.data import runtime
    from agent.briefing.sources import registry

    monkeypatch.setattr(runtime, "current_service", lambda: service)
    monkeypatch.setattr(registry, "_elearning_sources", lambda: [])
    monkeypatch.setattr(registry, "apple_calendar_connected", lambda: False)
    sources = registry.configured_sources()
    assert len(sources) == 1 and isinstance(sources[0], DataSource)
    from agent.briefing.pipeline import BriefingPipeline
    from tests.briefing_domain import BriefingService, BriefingStore
    from briefing_fakes import DeterministicBriefingModel
    from agent.briefing.generator import AgentBriefingGenerator
    from datetime import datetime, timezone

    consumer = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    result = BriefingPipeline(
        consumer,
        sources,
        generator=AgentBriefingGenerator(model=DeterministicBriefingModel()),
        clock=lambda: datetime(2026, 9, 9, 8, tzinfo=timezone.utc),
    ).run()
    assert result["mail"] and result["briefing"].status in {"completed", "partial"}
    assert service.query(service.list_sources()[0]["id"])["records"]
    assert all(row["source"] == "email" for row in result["mail"])
