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

    db = tmp_path / "bills.db"
    monkeypatch.setattr("core.services.bills_facade._db_path", lambda: db)

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


def test_uninstalled_bills_never_falls_back_to_a_host_database(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "0")
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="requires the stella.bills plugin"):
        Application.port("bills").list_ledger(2026, 10)
    assert not list(tmp_path.rglob("bills.db"))


def test_bills_export_uses_the_plugin_worker(tmp_path, monkeypatch):
    import zipfile
    from io import BytesIO

    from core.services.bills_facade import BillsPluginFacade

    package = Path(__file__).resolve().parents[2] / "Stella-Plugins/plugins/bills"
    monkeypatch.setenv("STELLA_BILLS_PLUGIN_ROOT", str(package))
    monkeypatch.setattr("core.services.bills_facade._db_path", lambda: tmp_path / "bills.db")
    service = BillsPluginFacade()
    service.create_ledger({"name": "午餐", "category": "消费", "entry_type": "expense",
                           "amount_minor": 3250, "occurred_at": "2026-10-19T12:00:00+08:00"})
    data = service.export_ledger("2026-10-01", "2026-10-31", lang="en")
    with zipfile.ZipFile(BytesIO(data)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "午餐" in sheet
    assert "-32.50" in sheet
    assert "Expense total" in sheet
    with pytest.raises(ValueError, match="start must be on or before end"):
        service.export_ledger("2026-10-31", "2026-10-01")
