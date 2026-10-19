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
