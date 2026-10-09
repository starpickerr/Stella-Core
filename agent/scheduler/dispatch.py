"""Bounded notification delivery with durable platform acceptance records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType


@dataclass(frozen=True)
class DeliveryOutcome:
    status: str
    error: str = ""
    retryable: bool = False


def _channel_for(channel_type):
    if channel_type == "weixin":
        from agent.scheduler.delivery import runtime_channel
        return runtime_channel("weixin")
    from channel.channel_factory import create_channel
    return create_channel(channel_type)


def _response_details(response):
    if not isinstance(response, dict):
        return {"accepted": response is not False}
    safe_keys = ("success", "ret", "errcode", "code", "message_id", "msg_id", "request_id")
    details = {key: response[key] for key in safe_keys if key in response and
               isinstance(response[key], (str, int, float, bool, type(None)))}
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("message_id"), str):
        details["message_id"] = data["message_id"]
    return details


def _one_delivery(store, delivery_id, leg, destination, content, *, agent_id, channel_provider):
    channel_type = destination["channel_type"]
    receiver = destination["receiver"]
    store.queue_delivery(delivery_id, leg, channel_type, receiver)
    decision = store.begin_delivery(delivery_id, leg, channel_type, receiver)
    if decision != "send":
        row = store.get_delivery(delivery_id, leg)
        return DeliveryOutcome(decision, row.get("error") or "" if row else "",
                               bool(row and row.get("retryable") and row.get("attempts", 0) < 3))

    channel = channel_provider(channel_type)
    if channel is None:
        error = f"{channel_type} is unavailable"
        store.finish_delivery(delivery_id, leg, "waiting", error=error)
        return DeliveryOutcome("waiting", error)
    if channel_type == "weixin":
        if getattr(channel, "login_status", "logged_in") != "logged_in":
            error = "Weixin login is required"
            store.finish_delivery(delivery_id, leg, "waiting", error=error)
            return DeliveryOutcome("waiting", error)
        tokens = getattr(channel, "_context_tokens", None)
        if tokens is not None and not tokens.get(receiver):
            error = "Weixin conversation context expired"
            store.finish_delivery(delivery_id, leg, "waiting", error=error)
            return DeliveryOutcome("waiting", error)

    context = Context(ContextType.TEXT, content)
    context["receiver"] = receiver
    context["isgroup"] = destination.get("is_group", False)
    context["session_id"] = destination.get("notify_session_id") or receiver
    context["channel_type"] = channel_type
    context["agent_id"] = agent_id
    context["scheduled_delivery"] = True
    if channel_type == "feishu":
        context["receive_id_type"] = destination.get("receive_id_type") or (
            "chat_id" if destination.get("is_group") else "open_id")
        context["msg"] = None
    if channel_type == "web":
        context["request_id"] = f"scheduled_{delivery_id}_{leg}"
        if hasattr(channel, "request_to_session"):
            channel.request_to_session[context["request_id"]] = receiver
    try:
        response = channel.send(Reply(ReplyType.TEXT, content), context)
        details = _response_details(response)
        if response is False or details.get("success") is False:
            error = "Channel rejected scheduled delivery"
            store.finish_delivery(delivery_id, leg, "failed", error=error,
                                  platform_response=details)
            return DeliveryOutcome("failed", error)
        store.finish_delivery(delivery_id, leg, "accepted", platform_response=details)
        return DeliveryOutcome("accepted")
    except (requests.exceptions.Timeout, TimeoutError) as exc:
        error = str(exc)[:500]
        store.finish_delivery(delivery_id, leg, "unknown", error=error)
        return DeliveryOutcome("unknown", error)
    except Exception as exc:
        error = str(exc)[:500]
        if channel_type == "weixin" and ("-14" in error or "context token expired" in error.lower()):
            status, retryable = "waiting", False
        else:
            status, retryable = "failed", isinstance(exc, (ConnectionError, requests.exceptions.ConnectionError))
        row = store.get_delivery(delivery_id, leg)
        retryable = retryable and row["attempts"] < 3
        store.finish_delivery(delivery_id, leg, status, error=error, retryable=retryable)
        return DeliveryOutcome(status, error, retryable)


def dispatch_notification(store, delivery_id, route, content, *, agent_id=None, expires_at=None,
                          now=None, channel_provider=None):
    """Attempt an explicit route once; only a saved opt-in permits backup."""
    if not isinstance(route, dict) or not isinstance(route.get("primary"), dict):
        raise ValueError("A primary notification destination is required")
    primary = route["primary"]
    store.queue_delivery(delivery_id, "primary", primary["channel_type"], primary["receiver"])
    recorded = store.get_delivery(delivery_id, "primary")
    backup_recorded = store.get_delivery(delivery_id, "backup")
    if (recorded and recorded["status"] == "accepted" or
            backup_recorded and backup_recorded["status"] == "accepted"):
        return DeliveryOutcome("accepted")
    if recorded and recorded["status"] in ("unknown", "sending"):
        if recorded["status"] == "sending":
            store.begin_delivery(delivery_id, "primary", primary["channel_type"], primary["receiver"])
        return DeliveryOutcome("unknown", recorded.get("error") or "Previous send outcome is unknown")
    instant = now or datetime.now(timezone.utc)
    if expires_at is not None and instant >= expires_at:
        store.expire_delivery(delivery_id, "primary", primary["channel_type"], primary["receiver"])
        return DeliveryOutcome("expired", "Notification is past its useful time")
    provider = channel_provider or _channel_for
    result = _one_delivery(store, delivery_id, "primary", primary, content,
                           agent_id=agent_id, channel_provider=provider)
    if result.status in ("accepted", "unknown") or not route.get("backup_enabled"):
        return result
    backup = route.get("backup")
    if not isinstance(backup, dict):
        raise ValueError("Enabled backup requires a destination")
    return _one_delivery(store, delivery_id, "backup", backup, content,
                         agent_id=agent_id, channel_provider=provider)
