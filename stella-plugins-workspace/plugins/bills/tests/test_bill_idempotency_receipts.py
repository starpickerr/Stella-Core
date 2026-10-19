"""Bills domainWrite: idempotency, conflict, revision in same DB transaction."""

from __future__ import annotations

import pytest

from stella_bills_domain.service import BillsService
from stella_bills_domain.store import BillStore


def _svc(tmp_path) -> BillsService:
    return BillsService(BillStore(tmp_path / "bills.db"))


def _lunch(**extra):
    payload = {
        "name": "午餐",
        "category": "消费",
        "entry_type": "expense",
        "amount_minor": 3200,
        "occurred_at": "2026-08-02T12:30:00+08:00",
    }
    payload.update(extra)
    return payload


def test_same_key_same_payload_does_not_duplicate(tmp_path):
    svc = _svc(tmp_path)
    first = svc.create_ledger(_lunch(), idempotency_key="k1")
    second = svc.create_ledger(_lunch(), idempotency_key="k1")
    assert first["id"] == second["id"]
    assert first["revision"] == second["revision"] == 1
    assert len(svc.list_ledger(2026, 8)) == 1


def test_same_key_different_payload_conflicts(tmp_path):
    svc = _svc(tmp_path)
    svc.create_ledger(_lunch(), idempotency_key="k2")
    with pytest.raises(ValueError, match="idempotency conflict"):
        svc.create_ledger(_lunch(amount_minor=3300), idempotency_key="k2")


def test_update_requires_expected_revision(tmp_path):
    svc = _svc(tmp_path)
    created = svc.create_ledger(_lunch(), idempotency_key="k3")
    assert created["revision"] == 1
    updated = svc.update_ledger(
        created["id"],
        {"name": "午餐改"},
        expected_revision=1,
        idempotency_key="k3u",
    )
    assert updated["revision"] == 2
    with pytest.raises(ValueError, match="revision conflict"):
        svc.update_ledger(
            created["id"],
            {"name": "再改"},
            expected_revision=1,
            idempotency_key="k3u2",
        )


def test_get_operation_receipt(tmp_path):
    svc = _svc(tmp_path)
    created = svc.create_ledger(_lunch(), idempotency_key="k4")
    receipt = svc.get_operation("k4")
    assert receipt is not None
    assert receipt["status"] == "succeeded"
    assert receipt["result_id"] == created["id"]
