"""Email schema: DDL lives in schema.sql."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

REQUIRED_TABLES = frozenset({"email_accounts", "email_cursors", "email_meta"})


def load_schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(load_schema_sql())


def missing_tables(db: sqlite3.Connection) -> set[str]:
    present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return set(REQUIRED_TABLES) - present
