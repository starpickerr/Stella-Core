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
    config['args'][config['args'].index('--user-id') + 1] = 'local-default'
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


@pytest.mark.parametrize('purpose', ['interactive', 'background'])
def test_native_briefing_email_inherits_live_owner_reads_only(integration, monkeypatch, purpose):
    from types import SimpleNamespace
    from agent.briefing.pipeline import BriefingPipeline
    from core.execution.context import execution_scope
    from core.plugins.authz import PluginAuthorizationStore
    from core.data.usage import UsageService
    from config import conf
    service, _, _ = integration
    source = service.list_sources()[0]
    adapter = DataSource(service, source, consumer_id='stella.briefing')
    authz = PluginAuthorizationStore()
    monkeypatch.setattr('core.mcp.authorization.DEFAULT_AUTHZ', authz)
    ref = f'email-default-grant:{purpose}:email.fetch'
    authz.issue_scoped(grant_ref=ref, parent_ref='email-default-grant', plugin_id='stella.email',
        user_id='local-default', consumer_plugin_id='stella.email', capability='email.fetch',
        methods=['fetch_messages'], resources=[{'kind': 'user', 'id': 'local-default'}], purpose=purpose)
    pipeline = BriefingPipeline(service=SimpleNamespace(get_cursor=lambda *args: None,
        store=SimpleNamespace(window_candidates=lambda *args: [])), generator=object())
    def collect():
        with execution_scope(origin='job' if purpose == 'background' else 'ui'):
            return pipeline._fetch_source(adapter, '2026-09-08T00:00:00Z', '2026-09-10T00:00:00Z')
    first = collect()
    assert first.items and first.items[0].payload['body']
    # Cached content must still go through the same checks.
    assert collect().items[0].source_id == first.items[0].source_id
    authz.revoke(ref)
    with pytest.raises(PermissionError):
        collect()
    authz.update_owned(ref, user_id='local-default', revision=2, revoked=False)
    assert collect().items
    UsageService(service).set('stella.briefing', source['id'], False)
    with pytest.raises(PermissionError, match='usage'):
        collect()
    UsageService(service).set('stella.briefing', source['id'], True)
    monkeypatch.setitem(conf(), 'security_policy', {'preset': 'full-access', 'rules': {},
        'connections': {'mcp:email': {'allowed': False}}})
    with pytest.raises(PermissionError):
        collect()


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
    from core.plugins.authz import PluginAuthorizationStore
    authz = PluginAuthorizationStore()
    monkeypatch.setattr('core.mcp.authorization.DEFAULT_AUTHZ', authz)
    authz.issue_scoped(grant_ref='email-default-grant:interactive:email.fetch',
        parent_ref='email-default-grant', plugin_id='stella.email', user_id='local-default',
        consumer_plugin_id='stella.email', capability='email.fetch', methods=['fetch_messages'],
        resources=[{'kind': 'user', 'id': 'local-default'}], purpose='interactive')
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
    assert result['briefing'].status == 'completed'
    assert service.query(service.list_sources()[0]["id"])["records"]
    assert all(row["source"] == "email" for row in result["mail"])


def test_standard_mcp_different_schema_is_mapped_once_for_all_consumers(
    tmp_path, monkeypatch
):
    from pathlib import Path
    from config import conf
    from agent.tools.tool_manager import ToolManager

    root = Path(__file__).resolve().parents[2]
    manager = ToolManager()
    config = {
        "name": "generic-source",
        "type": "stdio",
        "command": str(root / "MCP/email-mcp/.venv/bin/python"),
        "args": [str(Path(__file__).parent / "fixtures/generic_data_mcp.py")],
        "timeout": 10,
    }
    monkeypatch.setattr(manager, "_load_mcp_configs", lambda: [config])
    monkeypatch.setitem(conf(), "agent_permission_mode", "full-access")
    monkeypatch.setitem(
        conf(),
        "security_policy",
        {"preset": "full-access", "rules": {}, "connections": {}},
    )
    mapping = {
        "discover": "accounts",
        "discovery_rows": "accounts",
        "kind": "generic-mail",
        "account_field": "key",
        "name_field": "label",
        "source_args": {"account_id": "key"},
        "fetch": "messages",
        "options": {"since": "since", "until": "until"},
        "items": "messages",
        "cursors": "next",
        "cursor_argument": "page_token",
        "cursor_key": "page",
        "errors": None,
        "record_fields": {
            "source_id": "id",
            "title": "subject",
            "payload.body": "text",
            "occurred_at": "timestamp",
        },
    }
    providers = ProviderRegistry()
    providers.register("generic", McpProvider("generic-source", mapping, manager))
    service = DataService(tmp_path / "generic.db", providers)
    try:
        discovered = service.discover()
        assert not discovered["errors"] and len(discovered["sources"]) == 1
        source = discovered["sources"][0]
        sub = service.subscribe(source["id"], "second-consumer")
        result = DataSource(service, source).fetch(
            {"since": "2026-09-08T00:00:00Z", "until": "2026-09-10T00:00:00Z"}
        )
        assert (
            result.items[0].title == "Generic subject"
            and result.items[0].payload["body"] == "Generic body"
        )
        received = []
        assert service.dispatch(sub["id"], received.append)["delivered"] == 1
        assert received[0]["record"]["source_id"] == "message-a"
        assert service.sync(source["id"])["cursors"] == {"page": "next-page"}
        # A tool without incremental inputs omits the argument entirely.
        mapping.pop("cursor_argument")
        assert service.sync(source["id"])["cursors"] == {"page": "next-page"}
    finally:
        manager._teardown_mcp_server("generic-source")


def test_default_registered_consumer_delivers_sdk_records_to_real_briefing_worker(
    integration, monkeypatch, tmp_path
):
    from core.data.api import DataController
    from core.services import briefing_facade, briefing_gateway
    import sqlite3

    service, _, _ = integration
    source = service.list_sources()[0]
    sub = service.subscribe(source["id"], "briefing")
    service.sync(
        source["id"], {"since": "2026-09-08T00:00:00Z", "until": "2026-09-10T00:00:00Z"}
    )
    briefing_gateway.shutdown_briefing_session()
    path = tmp_path / "briefing-worker.db"
    monkeypatch.setattr(briefing_facade, "_db_path", lambda: path)
    try:
        outcome = DataController(service).command(
            {"action": "dispatch", "subscription_id": sub["id"]}
        )
        assert (
            outcome["delivery"]["delivered"] > 0 and outcome["delivery"]["failed"] == 0
        )
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT count(*) FROM source_items").fetchone()[0] > 0
    finally:
        briefing_gateway.shutdown_briefing_session()
