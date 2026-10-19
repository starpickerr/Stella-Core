import sqlite3

from stella_bills_domain.store import BillStore, clear_bill_store_cache, get_bill_store


_TABLES = {
    "financial_events",
    "planned_payments",
    "ledger_entries",
    "period_statements",
    "period_statement_items",
}


def test_creates_database_when_file_is_missing(tmp_path):
    db = tmp_path / "bills" / "bills.db"
    store = BillStore(db)

    assert store.created_new is True
    assert db.is_file()
    assert _TABLES.issubset(store.table_names())


def test_reuses_existing_database_without_recreating(tmp_path):
    db = tmp_path / "bills.db"
    first = BillStore(db)
    sqlite3.connect(str(db)).execute(
        """
        INSERT INTO financial_events (
            id, event_type, amount_minor, currency, category, name, note,
            created_at, updated_at
        ) VALUES (
            'evt-1', 'ledger_entry', 100, 'CNY', '消费', '午餐', '',
            '2026-08-25T00:00:00Z', '2026-08-25T00:00:00Z'
        )
        """
    ).connection.commit()

    second = BillStore(db)

    assert first.created_new is True
    assert second.created_new is False
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM financial_events").fetchone()[0]
    conn.close()
    assert count == 1


def test_get_bill_store_creates_once_per_path(tmp_path):
    clear_bill_store_cache()
    db = tmp_path / "bills.db"
    a = get_bill_store(db)
    b = get_bill_store(db)
    assert a is b
    clear_bill_store_cache()
