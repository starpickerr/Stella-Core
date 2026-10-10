"""OS notifications claimed by the logged-in desktop client."""

from __future__ import annotations

import threading


_lock = threading.Lock()
_pending = {}
_client_seen = False


def note_desktop_client():
    global _client_seen
    _client_seen = True


def desktop_client_seen():
    return _client_seen


def enqueue_desktop_notification(delivery_id, receiver, content):
    with _lock:
        _pending[delivery_id] = {
            "delivery_id": delivery_id,
            "claim_id": delivery_id,
            "receiver": receiver,
            "notification_title": "Stella",
            "title": "Stella",
            "body": content,
        }


def claim_desktop_notifications():
    with _lock:
        claimed = list(_pending.values())
        _pending.clear()
        return claimed


def acknowledge_desktop_notification(store, delivery_id, shown, error=""):
    if type(shown) is not bool:
        raise ValueError("shown must be true or false")
    status = "accepted" if shown else "failed"
    store.settle_delivery(delivery_id, "primary", status, error="" if shown else (error or "系统未允许通知"))
    return status
