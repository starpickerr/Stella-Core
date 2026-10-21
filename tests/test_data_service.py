"""Data Service invariants; providers are independent of business consumers."""

from dataclasses import replace
import pytest
from core.services.source_types import FetchedItem, FetchResult
from core.data.service import DataService, ProviderRegistry


class Provider:
    def __init__(self):
        self.allowed = True
        self.items = [
            FetchedItem(
                "message",
                "message-1",
                account_id="a",
                title="First",
                payload={"body": "content"},
            )
        ]
        self.calls = []
        self.errors = []

    def discover(self):
        return [
            {
                "id": "messages:a",
                "name": "Inbox",
                "kind": "message",
                "account_id": "a",
                "config": {},
            }
        ]

    def authorize(self, source, operation):
        self.calls.append(operation)
        if not self.allowed:
            raise PermissionError("source authorization revoked")

    def fetch(self, source, cursors, options):
        self.calls.append(("fetch", dict(cursors), dict(options)))
        return FetchResult(list(self.items), {"position": "2"}, list(self.errors))


@pytest.fixture
def env(tmp_path):
    provider = Provider()
    registry = ProviderRegistry()
    registry.register("messages", provider)
    service = DataService(tmp_path / "data.db", registry)
    service.discover()
    return service, provider


def test_discover_idempotent_and_source_switch_persists(env):
    service, provider = env
    service.discover()
    assert len(service.list_sources()) == 1
    service.configure_source("messages:a", enabled=False)
    service.discover()
    assert service.list_sources()[0]["enabled"] is False
    with pytest.raises(PermissionError, match="disabled"):
        service.sync("messages:a")
    assert not any(isinstance(call, tuple) for call in provider.calls)


def test_sync_dedup_and_changes_have_stable_record_identity(env):
    service, provider = env
    first = service.sync("messages:a")
    identifier = first["records"][0]["id"]
    assert len(service.query("messages:a")["records"]) == 1
    assert [row["type"] for row in service.events("messages:a")] == ["created"]
    service.sync("messages:a")
    assert len(service.events("messages:a")) == 1
    provider.items[0] = replace(provider.items[0], title="Changed")
    assert service.sync("messages:a")["records"][0]["id"] == identifier
    assert [row["type"] for row in service.events("messages:a")] == [
        "created",
        "updated",
    ]
    assert service.sync_state("messages:a")["cursors"] == {"position": "2"}
    service.delete_record(identifier)
    assert service.query("messages:a")["records"] == []
    assert service.events("messages:a")[-1]["type"] == "deleted"
    assert provider.items  # deleting cache must not mutate the provider


def test_record_event_and_cursor_commit_is_atomic(env, monkeypatch):
    service, _ = env

    def disk_failure(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service.store, "append_event", disk_failure)
    with pytest.raises(OSError, match="disk full"):
        service.sync("messages:a")
    assert service.query("messages:a")["records"] == []
    assert service.events("messages:a") == []
    assert service.sync_state("messages:a")["cursors"] == {}


def test_partial_fetch_does_not_advance_cursor(env):
    service, provider = env
    provider.errors = ["page two unavailable"]
    outcome = service.sync("messages:a")
    assert outcome["errors"] == provider.errors
    assert len(service.query("messages:a")["records"]) == 1
    assert service.sync_state("messages:a")["cursors"] == {}


def test_revocation_blocks_cached_reads_export_and_delivery(env):
    service, provider = env
    sub = service.subscribe("messages:a", "consumer-a")
    service.sync("messages:a")
    provider.allowed = False
    received = []
    for operation in [
        lambda: service.query("messages:a"),
        lambda: service.export("messages:a"),
        lambda: service.dispatch(sub["id"], received.append),
    ]:
        with pytest.raises(PermissionError, match="revoked"):
            operation()
    assert received == []
    provider.allowed = True
    assert service.dispatch(sub["id"], received.append)["delivered"] == 1


def test_independent_consumers_retry_with_stable_event_ids(env):
    service, _ = env
    a = service.subscribe("messages:a", "a")
    b = service.subscribe("messages:a", "b")
    service.sync("messages:a")
    received = []
    attempts = []

    def broken(event):
        attempts.append(event["id"])
        raise RuntimeError("offline consumer")

    assert service.dispatch(a["id"], broken)["failed"] == 1
    assert service.deliveries(a["id"])[0]["state"] == "failed"
    assert service.dispatch(b["id"], received.append)["delivered"] == 1
    assert service.dispatch(a["id"], received.append)["delivered"] == 1
    assert received[0]["id"] == received[1]["id"] == attempts[0]
    assert service.dispatch(a["id"], received.append)["delivered"] == 0


def test_reference_and_expired_cache_do_not_return_body(env):
    service, _ = env
    service.configure_source("messages:a", storage="reference")
    service.sync("messages:a")
    row = service.query("messages:a")["records"][0]
    assert row["item"]["payload"] == {} and row["item"]["snippet"] == ""
    service.configure_source("messages:a", storage="cache", retention_days=1)
    service.sync("messages:a")
    with service.store.connection() as db:
        db.execute("UPDATE records SET updated_at=0")
    assert service.query("messages:a")["records"] == []
    assert service.cleanup("messages:a")["removed"] == 1


def test_new_provider_and_two_consumers_require_no_existing_provider_changes(env):
    service, _ = env

    class Another(Provider):
        def __init__(self):
            super().__init__()
            self.items = [
                replace(item, source="calendar", account_id="b") for item in self.items
            ]

        def discover(self):
            return [
                {
                    "id": "calendar:b",
                    "name": "Calendar",
                    "kind": "event",
                    "account_id": "b",
                    "config": {},
                }
            ]

    service.providers.register("calendar", Another())
    service.discover()
    sub = service.subscribe("calendar:b", "other-consumer", filter={"q": "First"})
    service.sync("calendar:b")
    received = []
    assert service.dispatch(sub["id"], received.append)["delivered"] == 1
    assert len(service.list_sources()) == 2


def test_service_cannot_be_reused_across_users(env):
    service, _ = env
    from common.runtime_identity import identity_scope

    with identity_scope(user_id="someone-else"):
        with pytest.raises(PermissionError, match="user"):
            service.list_sources()


def test_disable_during_fetch_prevents_commit(env):
    service, provider = env
    original = provider.fetch

    def fetched(*args):
        value = original(*args)
        service.configure_source("messages:a", enabled=False)
        return value

    provider.fetch = fetched
    with pytest.raises(PermissionError, match="disabled"):
        service.sync("messages:a")
    service.configure_source("messages:a", enabled=True)
    assert service.query("messages:a")["records"] == []
    assert service.sync_state("messages:a")["cursors"] == {}


def test_provider_cannot_cross_account_boundary(env):
    service, provider = env
    provider.items[0] = replace(provider.items[0], account_id="another-account")
    with pytest.raises(PermissionError, match="bound source account"):
        service.sync("messages:a")
    assert service.query("messages:a")["records"] == []
    assert service.sync_state("messages:a")["cursors"] == {}


def test_reference_policy_applies_immediately_to_existing_records(env):
    service, _ = env
    service.sync("messages:a")
    service.configure_source("messages:a", storage="reference")
    assert service.query("messages:a")["records"][0]["item"]["payload"] == {}


def test_expired_delivery_lease_is_recovered_without_advancing_others(env):
    service, _ = env
    sub = service.subscribe("messages:a", "consumer")
    service.sync("messages:a")
    with service.store.connection() as db:
        db.execute(
            "UPDATE deliveries SET state='delivering',lease='crashed',lease_until=0"
        )
    received = []
    assert service.dispatch(sub["id"], received.append)["delivered"] == 1
    assert service.dispatch(sub["id"], received.append)["delivered"] == 0


def test_core_data_mutation_uses_high_risk_policy_without_network_access():
    from agent.permission.gateway import register_tool, Capability, SecurityGateway

    register_tool("data_manage", Capability.WORKSPACE_WRITE)
    blocked = {
        "preset": "full-access",
        "rules": {"high_risk": "deny"},
        "connections": {},
    }
    assert not SecurityGateway.check(
        "full-access",
        "data_manage",
        {"action": "delete"},
        policy=blocked,
        create_pending=False,
    ).allowed
    local = {
        "preset": "full-access",
        "rules": {"external": "deny", "network": "deny"},
        "connections": {},
    }
    assert SecurityGateway.check(
        "full-access",
        "data_manage",
        {"action": "delete"},
        policy=local,
        create_pending=False,
    ).allowed


def test_policy_change_while_reading_prevents_stale_body_return(env):
    service, provider = env
    service.sync("messages:a")
    original = provider.authorize
    reads = 0

    def changed(source, operation):
        nonlocal reads
        original(source, operation)
        if operation == "read":
            reads += 1
            if reads == 2:
                service.store.configure("messages:a", {"storage": "reference"})

    provider.authorize = changed
    with pytest.raises(PermissionError, match="changed"):
        service.query("messages:a")


@pytest.mark.parametrize(
    "tool,params",
    [
        ("read", lambda path: {"path": str(path)}),
        ("write", lambda path: {"path": str(path), "content": "overwrite"}),
        ("bash", lambda path: {"command": "sqlite3 " + str(path) + " .dump"}),
    ],
)
def test_generic_tools_cannot_bypass_data_service_permissions(
    tmp_path, monkeypatch, tool, params
):
    from agent.permission.gateway import SecurityGateway, Scope
    from common import state_dir

    monkeypatch.setattr(
        state_dir, "briefing_db", lambda **kwargs: tmp_path / "briefing/briefing.db"
    )
    monkeypatch.setattr(
        state_dir, "data_service_db", lambda **kwargs: tmp_path / "data/data.db"
    )
    decision = SecurityGateway.check(
        "full-access",
        tool,
        params(tmp_path / "data/data.db"),
        scope=Scope(write_roots=(str(tmp_path),)),
        create_pending=False,
    )
    assert not decision.allowed


def test_data_database_is_private_and_refuses_symlink_targets(tmp_path):
    import os
    from core.data.store import DataStore

    store = DataStore(tmp_path / "owned/data.db")
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o077 == 0
    target = tmp_path / "unrelated"
    target.write_text("preserve")
    link = tmp_path / "link/data.db"
    link.parent.mkdir()
    link.symlink_to(target)
    with pytest.raises(PermissionError, match="symlink"):
        DataStore(link)
    assert target.read_text() == "preserve"
