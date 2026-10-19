"""Retry independent calendar and todo projections from immutable revisions."""

from __future__ import annotations

import json
import logging
import threading
from types import SimpleNamespace

logger = logging.getLogger(__name__)

_locks = {}
_guard = threading.Lock()


def _lock_for(path):
    with _guard:
        return _locks.setdefault(str(path), threading.Lock())


def dispatch_pending(store, limit=20, todos=None, calendar=None):
    """Project ordered revisions; failed consumers keep their own pending ack."""
    if todos is None or calendar is None:
        # Peer business adapters live in the host; leave revisions pending (no error ack).
        return {"projected": 0, "pending": len(store.pending_projection_events(limit)),
                "reason": "adapters_unavailable"}
    projected = 0
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
                    from .actions import BriefingActions
                    BriefingActions(store, todos, calendar).sync(detail, consumer)
                    store.ack_projection(event["briefing_id"], event["revision"], consumer)
                    projected += 1
                except Exception as exc:
                    logger.exception(f"[BriefingOutbox] {consumer} projection failed")
                    store.ack_projection(event["briefing_id"], event["revision"], consumer, error=exc)
    return {"projected": projected, "pending": len(store.pending_projection_events(limit)), "reason": ""}
