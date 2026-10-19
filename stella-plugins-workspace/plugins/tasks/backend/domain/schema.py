"""Tasks schema: base DDL lives in schema.sql; legacy columns are added in place."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Columns added after the first release; existing databases receive them via ALTER.
_LATE_COLUMNS = (
    ("planned_on", "TEXT"), ("list_name", "TEXT NOT NULL DEFAULT ''"),
    ("tags", "TEXT NOT NULL DEFAULT '[]'"), ("flagged", "INTEGER NOT NULL DEFAULT 0"),
    ("checklist", "TEXT NOT NULL DEFAULT '[]'"),
    ("status", "TEXT NOT NULL DEFAULT 'todo'"), ("parent_id", "TEXT"),
    ("sort_order", "INTEGER NOT NULL DEFAULT 0"), ("remind_at", "TEXT"),
    ("reminder_delivery", "TEXT"), ("category_id", "TEXT"),
)

REQUIRED_TABLES = frozenset({
    "todos", "todo_completions", "todo_checklist_completions", "todo_dependencies",
    "todo_notifications", "reminder_occurrences", "reminder_deliveries",
    "reminder_route_deliveries", "todo_migrations", "briefing_applied",
    "source_tombstones", "todo_scheduler_links", "todo_categories",
})


def load_schema_sql() -> str:
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def ensure_schema(db: sqlite3.Connection) -> None:
    """Idempotently create or upgrade the Tasks schema on an open connection."""
    db.executescript(load_schema_sql())
    columns = {row[1] for row in db.execute("PRAGMA table_info(todos)")}
    for name, definition in _LATE_COLUMNS:
        if name not in columns:
            db.execute(f"ALTER TABLE todos ADD COLUMN {name} {definition}")
    db.execute("CREATE INDEX IF NOT EXISTS todos_parent_order ON todos(parent_id,sort_order,created_at)")
    if "status" not in columns:
        db.execute("UPDATE todos SET status='completed' WHERE completed_at IS NOT NULL")


def missing_tables(db: sqlite3.Connection) -> set[str]:
    present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return set(REQUIRED_TABLES) - present
