"""Automation schema migration entry (maintenance mode only)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_SCHEMA = Path(__file__).resolve().parent / "domain" / "schema.sql"
REQUIRED_TABLES = frozenset({"tasks"})


def _db_path(data_handle: dict[str, Any]) -> Path | None:
    raw = (data_handle or {}).get("dbPath")
    return Path(raw) if raw else None


def apply(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    """Create the task-rule table in place (idempotent; Core owns the other tables)."""
    path = _db_path(data_handle)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=10)
        try:
            db.executescript(_SCHEMA.read_text(encoding="utf-8"))
            db.commit()
        finally:
            db.close()
    return {"migrationId": migration_id, "applied": True, "schemaVersion": SCHEMA_VERSION}


def verify(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    path = _db_path(data_handle)
    missing: list[str] = []
    if path is not None:
        db = sqlite3.connect(str(path), timeout=10)
        try:
            present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            db.close()
        missing = sorted(REQUIRED_TABLES - present)
    return {"migrationId": migration_id, "verified": not missing,
            "schemaVersion": SCHEMA_VERSION, "missingTables": missing}
