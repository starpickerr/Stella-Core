"""Short lived confirmation tokens for scoped Apple sync previews."""

import secrets
import time


def _inventory(preview):
    """Counts that a confirmation must still match. The scan window moves with
    the clock and is not itself an inventory change."""
    return {key: value for key, value in preview.items() if key != "window"}


def prepare_scope(manager, source_ids, direction):
    with manager._lock:
        preview = manager.preview(source_ids, direction)
        if preview.get("failed_calendar_ids") or preview.get("failed_list_ids"):
            raise ValueError("selected Apple sources could not be fully scanned")
        token = secrets.token_urlsafe(24)
        manager._scope_preview = (token, tuple(source_ids), direction, preview, time.monotonic() + 600)
        return {"preview": preview, "preview_token": token}


def confirm_scope(manager, source_ids, direction, token):
    with manager._lock:
        pending = getattr(manager, "_scope_preview", None)
        if (not isinstance(token, str) or not pending or
                not secrets.compare_digest(token, pending[0]) or
                tuple(source_ids or ()) != pending[1] or direction != pending[2] or
                time.monotonic() > pending[4]):
            raise ValueError("matching Apple sync preview and confirmation are required")
        if _inventory(manager.preview(source_ids, direction)) != _inventory(pending[3]):
            manager._scope_preview = None
            raise ValueError("Apple sync inventory changed; preview again")
        manager._scope_preview = None


def prepare_items(manager, direction, source_id, item_ids):
    with manager._lock:
        preview = manager.preview_items(direction, source_id, item_ids)
        token = secrets.token_urlsafe(24)
        manager._item_preview = (token, direction, source_id, tuple(item_ids),
                                 preview, time.monotonic() + 600)
        return {"preview": preview, "preview_token": token}


def confirm_items(manager, direction, source_id, item_ids, token):
    with manager._lock:
        pending = getattr(manager, "_item_preview", None)
        if (not isinstance(token, str) or not pending or
                not secrets.compare_digest(token, pending[0]) or
                direction != pending[1] or source_id != pending[2] or
                tuple(item_ids or ()) != pending[3] or time.monotonic() > pending[5]):
            raise ValueError("matching Apple item preview and confirmation are required")
        if manager.preview_items(direction, source_id, item_ids) != pending[4]:
            manager._item_preview = None
            raise ValueError("Apple items changed; preview again")
        manager._item_preview = None
