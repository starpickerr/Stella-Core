from __future__ import annotations

from pathlib import Path

import pytest

from application.api import Application
from common.runtime_identity import RuntimeIdentity, use_identity


@pytest.fixture(autouse=True)
def _cleanup_gateway():
    yield
    from core.services import bills_gateway

    bills_gateway.shutdown_bills_session()


def test_application_port_routes_bills_via_plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "1")
    monkeypatch.setenv(
        "STELLA_BILLS_PLUGIN_ROOT",
        str(Path("stella-plugins-workspace/plugins/bills").resolve()),
    )
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))

    from agent.bills import store as bill_store

    db = tmp_path / "bills.db"

    def _store(db_path=None):
        return bill_store.BillStore(db if db_path is None else Path(db_path))

    monkeypatch.setattr(bill_store, "get_bill_store", _store)

    identity = RuntimeIdentity(agent_id="test-agent", user_id="test-user")
    with use_identity(identity):
        port = Application.port("bills")
        created = port.create_ledger(
            {
                "name": "咖啡",
                "category": "消费",
                "entry_type": "expense",
                "amount_minor": 1800,
                "occurred_at": "2026-10-19T09:00:00+08:00",
            }
        )
        assert created["amount_minor"] == 1800
        rows = port.list_ledger(2026, 10)
        assert len(rows) == 1


def test_repeated_business_operations_have_distinct_receipts(tmp_path, monkeypatch):
    from core.services.bills_facade import BillsPluginFacade

    monkeypatch.setenv("STELLA_BILLS_PLUGIN_ROOT", str(Path("stella-plugins-workspace/plugins/bills").resolve()))
    monkeypatch.setattr("core.services.bills_facade._db_path", lambda: tmp_path / "bills.db")
    service = BillsPluginFacade()
    payload = {"name": "午餐", "category": "消费", "entry_type": "expense",
               "amount_minor": 3200, "occurred_at": "2026-10-19T12:00:00+08:00"}
    first = service.create_ledger(payload)
    second = service.create_ledger(payload)
    assert first["id"] != second["id"]
    service.update_ledger(first["id"], {"name": "午餐改"})
    service.update_ledger(first["id"], {"amount_minor": 3500})
    assert service.get_ledger(first["id"])["amount_minor"] == 3500
    service.delete_ledger(first["id"])
    assert service.get_ledger(first["id"]) is None


def test_explicit_create_receipt_still_replays(tmp_path, monkeypatch):
    from core.services.bills_facade import BillsPluginFacade

    monkeypatch.setenv("STELLA_BILLS_PLUGIN_ROOT", str(Path("stella-plugins-workspace/plugins/bills").resolve()))
    monkeypatch.setattr("core.services.bills_facade._db_path", lambda: tmp_path / "bills.db")
    service = BillsPluginFacade()
    payload = {"name": "午餐", "category": "消费", "entry_type": "expense",
               "amount_minor": 3200, "occurred_at": "2026-10-19T12:00:00+08:00",
               "idempotencyKey": "request-1"}
    assert service.create_ledger(payload)["id"] == service.create_ledger(payload)["id"]
