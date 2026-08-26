"""SQLite persistence for the bills module.

On construct, the store checks whether the database file exists:
- missing file → create parent dirs, apply schema.sql, log a new database
- existing file → apply schema.sql with IF NOT EXISTS (no-op for current tables)
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Dict, Optional

from common.log import logger

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def load_schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


class BillStore:
    """SQLite-backed store. Schema is applied on every open so a new file
    is created automatically, and an existing file is left intact."""

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._lock = threading.RLock()
        self.created_new = not self._db_path.exists()
        self._init_db()

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._raw_connect()
        try:
            conn.executescript(load_schema_sql())
            conn.commit()
        finally:
            conn.close()
        if self.created_new:
            logger.info(f"[BillStore] Created new bills database at {self._db_path}")
        else:
            logger.info(f"[BillStore] Using existing bills database at {self._db_path}")

    def table_names(self) -> set:
        conn = self._raw_connect()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            return {row[0] for row in rows}
        finally:
            conn.close()

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn


_store_instances: Dict[str, BillStore] = {}
_store_lock = threading.RLock()


def get_bill_store(db_path: Optional[Path] = None) -> BillStore:
    """Return the bills store for ``db_path``, creating the file if missing.

    Omitting ``db_path`` uses the current identity's bills database under
    the agent workspace (``<workspace>/bills/bills.db`` on a single-agent
    install).
    """
    if db_path is None:
        from common.state_dir import bills_db

        db_path = bills_db()
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
