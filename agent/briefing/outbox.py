"""Retry independent calendar and todo projections from immutable revisions."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from common.log import logger

_locks = {}
_guard = threading.Lock()


def _lock_for(path):
    with _guard:
        return _locks.setdefault(str(path), threading.Lock())


def dispatch_pending(store, limit=20):
    """Project ordered revisions; failed consumers keep their own pending ack."""
    with _lock_for(store._db_path):
        events = store.pending_projection_events(limit)
        for event in events:
            snapshot = json.loads(event["snapshot"])
            detail = {
                "briefing": SimpleNamespace(**snapshot["briefing"]),
                "items": [SimpleNamespace(**item) for item in snapshot["items"]],
                "mail": snapshot.get("mail", []),
            }
            for consumer in ("calendar", "todo"):
                if event[f"{consumer}_ack_at"]:
                    continue
                try:
                    if consumer == "calendar":
                        from agent.calendar import CalendarService
                        CalendarService().ingest_briefing_revision(detail, event["revision"])
                    else:
                        from agent.todos import TodoService
                        TodoService().ingest_briefing_revision(detail, event["revision"])
                    store.ack_projection(event["briefing_id"], event["revision"], consumer)
                except Exception as exc:
                    logger.exception(f"[BriefingOutbox] {consumer} projection failed")
                    store.ack_projection(event["briefing_id"], event["revision"], consumer, error=exc)
