"""Briefing schema migration entry (maintenance mode only)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.store import BriefingStore

SCHEMA_VERSION = 1

REQUIRED_TABLES = frozenset({
    "source_items", "email_messages", "briefings", "briefing_items", "briefing_candidates",
    "filter_rules", "sync_state", "briefing_revisions", "briefing_mail",
    "briefing_source_staging", "briefing_source_errors", "briefing_outbox",
    "briefing_entities", "briefing_entity_items", "briefing_actions",
    "briefing_action_rules", "briefing_preferences",
})


def _db_path(data_handle: dict[str, Any]) -> Path | None:
    raw = (data_handle or {}).get("dbPath")
    return Path(raw) if raw else None


def apply(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    """Create or upgrade the briefing schema in place (idempotent)."""
    path = _db_path(data_handle)
    if path is not None:
        from domain.actions import BriefingActions

        store = BriefingStore(path)  # applies schema.sql + additive column upgrades
        BriefingActions(store)  # applies actions.sql
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
    return {
        "migrationId": migration_id,
        "verified": not missing,
        "schemaVersion": SCHEMA_VERSION,
        "missingTables": missing,
    }
