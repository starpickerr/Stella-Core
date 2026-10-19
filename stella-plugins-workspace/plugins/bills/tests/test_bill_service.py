import pytest

from stella_bills_domain.service import BillsService
from stella_bills_domain.store import BillStore


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


def test_failed_yearly_statement_does_not_keep_a_partial_ledger(tmp_path, monkeypatch):
    import sqlite3

    svc = _service(tmp_path)
    original = svc.store.replace_statement_items

    def fail_yearly(statement_id, items):
        statement = svc.store.get_statement(statement_id)
        if statement and statement["period_type"] == "yearly":
            raise sqlite3.OperationalError("database is locked")
        return original(statement_id, items)

    monkeypatch.setattr(svc.store, "replace_statement_items", fail_yearly)
    with pytest.raises(sqlite3.OperationalError):
        svc.create_ledger(_lunch())
    assert svc.store.list_ledgers() == []
    assert svc.list_statements() == []
    monkeypatch.undo()
    saved = svc.create_ledger(_lunch())
    assert svc.store.get_ledger(saved["id"])["name"] == "午餐"
    assert len(svc.list_statements("yearly", 2026)) == 1


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


def test_list_ledger_between_is_inclusive(tmp_path):
    svc = _service(tmp_path)
    svc.create_ledger(_lunch())
    svc.create_ledger(_lunch(occurred_at="2026-07-08T12:20:00+08:00", name="七月午餐"))
    svc.create_ledger(_lunch(occurred_at="2026-08-31T23:50:00+08:00", name="月末晚餐"))

    rows = svc.list_ledger_between("2026-08-01", "2026-08-31")
    assert [row["name"] for row in rows] == ["午餐", "月末晚餐"]

    with pytest.raises(ValueError, match="start must be on or before end"):
        svc.list_ledger_between("2026-08-31", "2026-08-01")


def test_ledger_xlsx_contains_rows_and_totals(tmp_path):
    import zipfile
    from io import BytesIO

    from stella_bills_domain.export import build_ledger_xlsx

    svc = _service(tmp_path)
    svc.create_ledger(_lunch())
    svc.create_ledger(
        {
            "name": "月薪",
            "category": "工资",
            "entry_type": "income",
            "amount_minor": 1200000,
            "occurred_at": "2026-08-01T09:00:00+08:00",
        }
    )
    data = build_ledger_xlsx(
        svc.list_ledger_between("2026-08-01", "2026-08-31"),
        start="2026-08-01",
        end="2026-08-31",
        lang="zh",
    )
    assert data[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(data)) as zf:
        xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "午餐" in xml
    assert "月薪" in xml
    assert "-32.00" in xml
    assert "12000.00" in xml
    assert "收入合计" in xml

