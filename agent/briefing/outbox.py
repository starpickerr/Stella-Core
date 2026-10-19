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
    delegate = getattr(store, "dispatch_outbox", None)
    if delegate is not None:  # plugin-backed store proxy (STELLA_BRIEFING_PLUGIN)
        return delegate(limit)
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
                    from agent.briefing.actions import BriefingActions
                    BriefingActions(store).sync(detail, consumer)
                    store.ack_projection(event["briefing_id"], event["revision"], consumer)
                except Exception as exc:
                    logger.exception(f"[BriefingOutbox] {consumer} projection failed")
                    store.ack_projection(event["briefing_id"], event["revision"], consumer, error=exc)
