"""eLearning data migration entry (maintenance mode only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from domain.store import ElearningStore

SCHEMA_VERSION = 1
_MARKER = "elearning-schema.json"


def _root(data_handle: dict[str, Any]) -> Path | None:
    raw = (data_handle or {}).get("dataDir")
    return Path(raw) if raw else None


def apply(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    """Create the data directory and adopt a legacy briefing directory (idempotent)."""
    root = _root(data_handle)
    imported: dict[str, Any] = {"imported": False}
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        legacy = (data_handle or {}).get("legacyDir")
        if legacy:
            imported = ElearningStore(root).import_legacy(legacy)
        (root / _MARKER).write_text(json.dumps({"schemaVersion": SCHEMA_VERSION}), encoding="utf-8")
    return {"migrationId": migration_id, "applied": True, "schemaVersion": SCHEMA_VERSION,
            "legacy": imported}


def verify(migration_id: str, data_handle: dict[str, Any]) -> dict[str, Any]:
    root = _root(data_handle)
    missing: list[str] = []
    if root is not None:
        try:
            version = json.loads((root / _MARKER).read_text(encoding="utf-8")).get("schemaVersion")
        except (OSError, ValueError):
            version = None
        if version != SCHEMA_VERSION:
            missing.append(_MARKER)
    return {"migrationId": migration_id, "verified": not missing, "schemaVersion": SCHEMA_VERSION,
            "missingTables": missing}
