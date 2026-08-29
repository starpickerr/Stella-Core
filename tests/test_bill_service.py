import pytest

from agent.bills.service import BillsService
from agent.bills.store import BillStore


def _service(tmp_path) -> BillsService:
    return BillsService(BillStore(tmp_path / "bills.db"))


def _lunch(amount=3200, occurred_at="2026-08-02T12:30:00+08:00", **extra):
    payload = {
        "name": "午餐",
        "category": "消费",
        "entry_type": "expense",
        "amount_minor": amount,
        "occurred_at": occurred_at,
    }
    payload.update(extra)
    return payload


def test_create_ledger_rebuilds_monthly_and_yearly_statements(tmp_path):
    svc = _service(tmp_path)
    entry = svc.create_ledger(_lunch())
    salary = svc.create_ledger(
        {
            "name": "月薪",
            "category": "工资",
            "entry_type": "income",
            "amount_minor": 1200000,
            "occurred_at": "2026-08-01T09:00:00+08:00",
        }
    )

    assert entry["name"] == "午餐"
    assert salary["entry_type"] == "income"

    monthly = [row for row in svc.list_statements("monthly", 2026) if row["month"] == 8]
    assert len(monthly) == 1
    assert monthly[0]["income_minor"] == 1200000
    assert monthly[0]["expense_minor"] == 3200
    assert monthly[0]["net_minor"] == 1200000 - 3200

    yearly = svc.list_statements("yearly", 2026)
    assert len(yearly) == 1
    assert yearly[0]["expense_minor"] == 3200

    detail = svc.get_statement(monthly[0]["id"])
    names = {(item["category"], item["name"], item["entry_type"]) for item in detail["items"]}
    assert ("消费", "午餐", "expense") in names
    assert ("工资", "月薪", "income") in names


def test_list_ledger_filters_by_year_month(tmp_path):
    svc = _service(tmp_path)
    svc.create_ledger(_lunch())
    svc.create_ledger(_lunch(occurred_at="2026-07-08T12:20:00+08:00", name="七月午餐"))

    august = svc.list_ledger(2026, 8)
    assert [row["name"] for row in august] == ["午餐"]


def test_update_amount_refreshes_totals(tmp_path):
    svc = _service(tmp_path)
    entry = svc.create_ledger(_lunch())
    svc.update_ledger(entry["id"], {"amount_minor": 5000})

    monthly = svc.list_statements("monthly", 2026)[0]
    assert monthly["expense_minor"] == 5000


def test_moving_entry_to_another_month_rebuilds_both(tmp_path):
    svc = _service(tmp_path)
    entry = svc.create_ledger(_lunch())
    svc.update_ledger(entry["id"], {"occurred_at": "2026-07-03T10:00:00+08:00"})

    assert svc.list_ledger(2026, 8) == []
    assert len(svc.list_ledger(2026, 7)) == 1
    assert svc.list_statements("monthly", 2026)[0]["month"] == 7


def test_delete_last_entry_removes_statements(tmp_path):
    svc = _service(tmp_path)
    entry = svc.create_ledger(_lunch())
    svc.delete_ledger(entry["id"])

    assert svc.list_statements("monthly") == []
    assert svc.list_statements("yearly") == []
    assert svc.get_ledger(entry["id"]) is None


def test_two_same_items_merge_in_statement(tmp_path):
    svc = _service(tmp_path)
    svc.create_ledger(_lunch())
    svc.create_ledger(_lunch(occurred_at="2026-08-03T13:00:00+08:00"))

    monthly = svc.list_statements("monthly", 2026)[0]
    items = svc.get_statement(monthly["id"])["items"]
    lunch = next(item for item in items if item["name"] == "午餐")
    assert lunch["entry_count"] == 2
    assert lunch["amount_minor"] == 6400


def test_validation_rejects_bad_payloads(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(ValueError, match="name"):
        svc.create_ledger(_lunch(name="  "))
    with pytest.raises(ValueError, match="amount_minor"):
        svc.create_ledger(_lunch(amount=0))
    with pytest.raises(ValueError, match="entry_type"):
        svc.create_ledger(_lunch(entry_type="transfer"))
    with pytest.raises(ValueError, match="occurred_at"):
        svc.create_ledger(_lunch(occurred_at="not-a-date"))
    with pytest.raises(KeyError):
        svc.delete_ledger("missing")
