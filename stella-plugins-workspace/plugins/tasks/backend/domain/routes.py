"""Notification route validation (vendored; no host scheduler import)."""

from __future__ import annotations

PROACTIVE = ("desktop", "telegram", "wecom_bot")


def normalize_notification_route(route, agent_id=None):
    """Normalize one new proactive destination. Backup fields are rejected."""
    if route is None:
        return {"primary": None, "needs_reselect": False}
    if not isinstance(route, dict):
        raise ValueError("notification route must be an object")
    if route.get("backup_enabled") is True or route.get("backup") not in (None,):
        raise ValueError("备用渠道已移除")
    primary = route.get("primary")
    if primary is None:
        return {"primary": None, "needs_reselect": False}
    channel_type = primary.get("channel_type") if isinstance(primary, dict) else None
    if channel_type not in PROACTIVE:
        raise ValueError("需要重新选择渠道")
    return {"primary": normalize_proactive_destination(primary, agent_id), "needs_reselect": False}


def normalize_proactive_destination(destination, agent_id=None):
    if not isinstance(destination, dict):
        raise ValueError("delivery must be an object")
    channel_type = destination.get("channel_type")
    if channel_type not in PROACTIVE:
        raise ValueError("需要重新选择渠道")
    receiver = destination.get("receiver")
    if channel_type == "desktop" and receiver in (None, ""):
        receiver = "desktop"
    if not isinstance(receiver, str) or not receiver.strip() or len(receiver.strip()) > 200:
        raise ValueError("A destination recipient is required")
    receiver = receiver.strip()
    is_group = destination.get("is_group", False)
    if type(is_group) is not bool:
        raise ValueError("is_group must be true or false")
    if channel_type == "desktop" and is_group:
        raise ValueError("This destination does not support group delivery")
    name = destination.get("receiver_name") or receiver
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError("recipient name must be at most 200 characters")
    return {"channel_type": channel_type, "receiver": receiver, "is_group": is_group,
            "receiver_name": name, "notify_session_id": receiver}


def load_saved_route(route):
    """Keep a stored primary and drop any backup. Legacy channels need a new choice."""
    if not isinstance(route, dict):
        return {"primary": None, "needs_reselect": False}
    primary = route.get("primary")
    if not isinstance(primary, dict):
        return {"primary": None, "needs_reselect": False}
    channel_type = primary.get("channel_type")
    return {"primary": primary, "needs_reselect": channel_type not in PROACTIVE}


def same_notification_route(candidate, saved):
    """Compare user choices while ignoring server-added recipient metadata."""
    if not isinstance(candidate, dict) or not isinstance(saved, dict):
        return False

    def identity(destination):
        if destination is None:
            return None
        if not isinstance(destination, dict):
            return False
        channel = destination.get("channel_type")
        group = destination.get("is_group", False)
        return (channel, destination.get("receiver"), group,
                destination.get("receive_id_type") or ("chat_id" if group else "open_id") if channel == "feishu" else None)

    return identity(candidate.get("primary")) == identity(saved.get("primary"))
