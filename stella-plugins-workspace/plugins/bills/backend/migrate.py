"""Bills schema migration entry (maintenance mode only)."""

from __future__ import annotations

from typing import Any


def apply(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    # Schema currently evolves via IF NOT EXISTS; record no-op apply.
    return {"migrationId": migration_id, "applied": True, "schemaVersion": 1}


def verify(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    return {"migrationId": migration_id, "verified": True, "schemaVersion": 1}
