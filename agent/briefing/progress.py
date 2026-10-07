"""Transient briefing drafts for the authenticated desktop client.

Previews never touch the catalog, revisions, cursors, or completed briefing.
The pipeline publishes them only while a run is active.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading

from common.state_dir import briefing_db

_lock = threading.RLock()
_active: dict[str, dict] = {}


def _key() -> str:
    return str(briefing_db(ensure=False).resolve())


def begin(briefing_id: str, total_sources: int) -> None:
    with _lock:
        _active[_key()] = {"briefing_id": briefing_id, "body": "", "stage": "fetching",
                           "completed_sources": 0, "total_sources": total_sources,
                           "candidate_count": 0, "updated_at": None}


def update(briefing_id: str, **fields) -> None:
    with _lock:
        value = _active.get(_key())
        if value and value["briefing_id"] == briefing_id:
            value.update(fields)
            value["updated_at"] = datetime.now(timezone.utc).isoformat()


def snapshot() -> dict | None:
    with _lock:
        value = _active.get(_key())
        return dict(value) if value else None


def finish(briefing_id: str) -> None:
    with _lock:
        key = _key()
        if _active.get(key, {}).get("briefing_id") == briefing_id:
            _active.pop(key, None)
