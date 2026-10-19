from __future__ import annotations

from pathlib import Path

import pytest

from core.services import bills_gateway


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    bills_gateway.shutdown_bills_session()


def test_bills_plugin_create_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_BILLS_PLUGIN", "1")
    monkeypatch.setenv(
        "STELLA_BILLS_PLUGIN_ROOT",
        str(Path("stella-plugins-workspace/plugins/bills").resolve()),
    )
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    db = tmp_path / "bills.db"
    created = bills_gateway.invoke_bills(
        "create_ledger",
        {
            "name": "午餐",
            "category": "消费",
            "entry_type": "expense",
            "amount_minor": 3200,
            "occurred_at": "2026-08-02T12:30:00+08:00",
            "idempotencyKey": "op-lunch-1",
        },
        db_path=db,
    )
    assert created["status"] == "succeeded"
    assert created["value"]["amount_minor"] == 3200
    listed = bills_gateway.invoke_bills(
        "list_ledger",
        {"year": 2026, "month": 8},
        db_path=db,
    )
    assert listed["status"] == "succeeded"
    assert len(listed["value"]) == 1
