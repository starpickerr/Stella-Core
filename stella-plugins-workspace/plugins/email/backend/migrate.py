"""Email schema migration entry (maintenance mode only)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.schema import ensure_schema, missing_tables

SCHEMA_VERSION = 1


def _db_path(data_handle: dict[str, Any]) -> Path | None:
    raw = (data_handle or {}).get("dbPath")
    return Path(raw) if raw else None


def apply(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    """Create or upgrade the Email schema in place (idempotent).

    A ``legacyMailboxPath`` handle entry is adopted by the service on first open,
    not here, so migration never reads credentials it does not need.
    """
    path = _db_path(data_handle)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(path), timeout=10)
        try:
            ensure_schema(db)
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
            missing = sorted(missing_tables(db))
        finally:
            db.close()
    return {
        "migrationId": migration_id,
        "verified": not missing,
        "schemaVersion": SCHEMA_VERSION,
        "missingTables": missing,
    }
