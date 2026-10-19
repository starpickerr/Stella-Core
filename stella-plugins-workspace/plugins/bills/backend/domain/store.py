"""SQLite persistence for the bills module.

On construct, the store checks whether the database file exists:
- missing file → create parent dirs, apply schema.sql, log a new database
- existing file → apply schema.sql with IF NOT EXISTS (no-op for current tables)
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import logging
logger = logging.getLogger('stella.bills')

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_LEDGER_SELECT = """
SELECT
    e.id,
    e.amount_minor,
    e.currency,
    e.category,
    e.name,
    e.note,
    e.created_at,
    e.updated_at,
    COALESCE(e.revision, 1) AS revision,
    l.entry_type,
    l.txn_type,
    l.counterparty,
    l.occurred_at,
    l.status,
    l.account_id,
    l.planned_payment_id
FROM financial_events e
JOIN ledger_entries l ON l.event_id = e.id
WHERE e.event_type = 'ledger_entry'
"""


def load_schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def _row_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


class BillStore:
    """SQLite-backed store. Schema is applied on every open so a new file
    is created automatically, and an existing file is left intact."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self._tx = threading.local()
        self.created_new = not self._db_path.exists()
        self._init_db()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._raw_connect()
        try:
            conn.executescript(load_schema_sql())
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(financial_events)").fetchall()
            }
            if "revision" not in columns:
                conn.execute(
                    "ALTER TABLE financial_events ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                )
            conn.commit()
        finally:
            conn.close()
        if self.created_new:
            logger.info(f"[BillStore] Created new bills database at {self._db_path}")
        else:
            logger.info(f"[BillStore] Using existing bills database at {self._db_path}")

    def table_names(self) -> set:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            return {row[0] for row in rows}

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run several store calls as one commit. Nested calls join the open transaction."""
        current = getattr(self._tx, "conn", None)
        if current is not None:
            yield current
            return
        with self._lock:
            conn = self._raw_connect()
            self._tx.conn = conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._tx.conn = None
                conn.close()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        current = getattr(self._tx, "conn", None)
        if current is not None:
            yield current
            return
        with self.transaction() as conn:
            yield conn

    # ------------------------------------------------------------------
    # Ledger
    # ------------------------------------------------------------------

    def get_ledger(self, entry_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                _LEDGER_SELECT + " AND e.id = ?", (entry_id,)
            ).fetchone()
            return _row_dict(row) if row else None

    def list_ledgers(self) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                _LEDGER_SELECT + " ORDER BY l.occurred_at ASC, e.id ASC"
            ).fetchall()
            return [_row_dict(row) for row in rows]

    def insert_ledger(self, entry: dict) -> dict:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO financial_events (
                    id, event_type, amount_minor, currency, category, name, note,
                    created_at, updated_at, revision
                ) VALUES (?, 'ledger_entry', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["id"],
                    entry["amount_minor"],
                    entry["currency"],
                    entry["category"],
                    entry["name"],
                    entry["note"],
                    entry["created_at"],
                    entry["updated_at"],
                    int(entry.get("revision") or 1),
                ),
            )
            conn.execute(
                """
                INSERT INTO ledger_entries (
                    event_id, entry_type, txn_type, counterparty, occurred_at,
                    status, account_id, planned_payment_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["id"],
                    entry["entry_type"],
                    entry["txn_type"],
                    entry["counterparty"],
                    entry["occurred_at"],
                    entry["status"],
                    entry.get("account_id"),
                    entry.get("planned_payment_id"),
                ),
            )
        return self.get_ledger(entry["id"])

    def update_ledger(self, entry: dict) -> Optional[dict]:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE financial_events
                SET amount_minor = ?, currency = ?, category = ?, name = ?,
                    note = ?, updated_at = ?, revision = ?
                WHERE id = ? AND event_type = 'ledger_entry'
                """,
                (
                    entry["amount_minor"],
                    entry["currency"],
                    entry["category"],
                    entry["name"],
                    entry["note"],
                    entry["updated_at"],
                    int(entry.get("revision") or 1),
                    entry["id"],
                ),
            )
            if cur.rowcount == 0:
                return None
            conn.execute(
                """
                UPDATE ledger_entries
                SET entry_type = ?, txn_type = ?, counterparty = ?,
                    occurred_at = ?, status = ?, account_id = ?,
                    planned_payment_id = ?
                WHERE event_id = ?
                """,
                (
                    entry["entry_type"],
                    entry["txn_type"],
                    entry["counterparty"],
                    entry["occurred_at"],
                    entry["status"],
                    entry.get("account_id"),
                    entry.get("planned_payment_id"),
                    entry["id"],
                ),
            )
        return self.get_ledger(entry["id"])

    def delete_ledger(self, entry_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM financial_events WHERE id = ? AND event_type = 'ledger_entry'",
                (entry_id,),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Period statements
    # ------------------------------------------------------------------

    def get_statement(self, statement_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM period_statements WHERE id = ?", (statement_id,)
            ).fetchone()
            return _row_dict(row) if row else None

    def get_statement_by_period(
        self,
        period_type: str,
        year: int,
        month: Optional[int],
        currency: str,
    ) -> Optional[dict]:
        with self._conn() as conn:
            if period_type == "yearly":
                row = conn.execute(
                    """
                    SELECT * FROM period_statements
                    WHERE period_type = 'yearly' AND year = ? AND month IS NULL
                      AND currency = ?
                    """,
                    (year, currency),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM period_statements
                    WHERE period_type = 'monthly' AND year = ? AND month = ?
                      AND currency = ?
                    """,
                    (year, month, currency),
                ).fetchone()
            return _row_dict(row) if row else None

    def list_statements(
        self, period_type: Optional[str] = None, year: Optional[int] = None
    ) -> List[dict]:
        clauses = []
        args: list = []
        if period_type:
            clauses.append("period_type = ?")
            args.append(period_type)
        if year is not None:
            clauses.append("year = ?")
            args.append(year)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM period_statements {where}
                ORDER BY year DESC, month DESC
                """,
                args,
            ).fetchall()
            return [_row_dict(row) for row in rows]

    def list_statement_items(self, statement_id: str) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM period_statement_items
                WHERE statement_id = ?
                ORDER BY entry_type ASC, amount_minor DESC, name ASC
                """,
                (statement_id,),
            ).fetchall()
            return [_row_dict(row) for row in rows]

    def upsert_statement(self, statement: dict) -> dict:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO period_statements (
                    id, period_type, year, month, start_at, end_at, currency,
                    income_minor, expense_minor, net_minor, status, note,
                    generated_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    start_at = excluded.start_at,
                    end_at = excluded.end_at,
                    income_minor = excluded.income_minor,
                    expense_minor = excluded.expense_minor,
                    net_minor = excluded.net_minor,
                    note = excluded.note,
                    generated_at = excluded.generated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    statement["id"],
                    statement["period_type"],
                    statement["year"],
                    statement["month"],
                    statement["start_at"],
                    statement["end_at"],
                    statement["currency"],
                    statement["income_minor"],
                    statement["expense_minor"],
                    statement["net_minor"],
                    statement["status"],
                    statement["note"],
                    statement["generated_at"],
                    statement["created_at"],
                    statement["updated_at"],
                ),
            )
        return self.get_statement(statement["id"])

    def replace_statement_items(self, statement_id: str, items: List[dict]) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM period_statement_items WHERE statement_id = ?",
                (statement_id,),
            )
            conn.executemany(
                """
                INSERT INTO period_statement_items (
                    id, statement_id, category, name, entry_type,
                    amount_minor, entry_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["id"],
                        statement_id,
                        item["category"],
                        item["name"],
                        item["entry_type"],
                        item["amount_minor"],
                        item["entry_count"],
                    )
                    for item in items
                ],
            )

    def delete_statement(self, statement_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM period_statements WHERE id = ?", (statement_id,)
            )
            return cur.rowcount > 0

    def get_operation_receipt(self, operation_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT operation_id, method, request_digest, status, result_id,
                       error_code, created_at, updated_at
                FROM plugin_operation_receipts WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            return _row_dict(row) if row else None

    def put_operation_receipt(self, receipt: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO plugin_operation_receipts (
                    operation_id, method, request_digest, status, result_id,
                    error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation_id) DO UPDATE SET
                    status=excluded.status,
                    result_id=excluded.result_id,
                    error_code=excluded.error_code,
                    updated_at=excluded.updated_at
                """,
                (
                    receipt["operation_id"],
                    receipt["method"],
                    receipt["request_digest"],
                    receipt["status"],
                    receipt.get("result_id"),
                    receipt.get("error_code"),
                    receipt["created_at"],
                    receipt["updated_at"],
                ),
            )


_store_instances: Dict[str, BillStore] = {}
_store_lock = threading.RLock()


def get_bill_store(db_path: Optional[Path] = None) -> BillStore:
    """Return the bills store for ``db_path``, creating the file if missing.

    Omitting ``db_path`` uses the current identity's bills database under
    the agent workspace (``<workspace>/bills/bills.db`` on a single-agent
    install).
    """
    if db_path is None:
        raise RuntimeError("db_path required in plugin worker")
    key = str(Path(db_path).resolve())
    store = _store_instances.get(key)
    if store is not None:
        return store
    with _store_lock:
        store = _store_instances.get(key)
        if store is None:
            store = BillStore(Path(db_path))
            _store_instances[key] = store
        return store


def clear_bill_store_cache() -> None:
    """Forget cached store objects. Intended for tests."""
    with _store_lock:
        _store_instances.clear()
