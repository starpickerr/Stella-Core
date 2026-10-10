"""OS notifications claimed by the logged-in desktop client."""

from __future__ import annotations

import threading


_lock = threading.Lock()
_pending = {}
_handed_out = set()
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


def claim_desktop_notifications(store=None):
    with _lock:
        if store is not None:
            for row in store.list_waiting_deliveries("desktop"):
                delivery_id = row["job_run_id"]
                if delivery_id in _handed_out or delivery_id in _pending:
                    continue
                payload = row.get("platform_response") or {}
                body = payload.get("body") if isinstance(payload, dict) else ""
                _pending[delivery_id] = {
                    "delivery_id": delivery_id,
                    "claim_id": delivery_id,
                    "receiver": row.get("receiver") or "",
                    "notification_title": "Stella",
                    "title": "Stella",
                    "body": body or "",
                }
        claimed = list(_pending.values())
        _handed_out.update(item["delivery_id"] for item in claimed)
        _pending.clear()
        return claimed


def reset_desktop_notifications():
    """Test hook for a process restart. Production claims survive in the store."""
    with _lock:
        _pending.clear()
        _handed_out.clear()


def acknowledge_desktop_notification(store, delivery_id, shown, error=""):
    if type(shown) is not bool:
        raise ValueError("shown must be true or false")
    status = "accepted" if shown else "failed"
    store.settle_delivery(delivery_id, "primary", status, error="" if shown else (error or "系统未允许通知"))
    return status
