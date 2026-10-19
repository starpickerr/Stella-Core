"""Trusted caller identity and serialization for the single-user worker slots."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import os
from threading import RLock

from common.runtime_identity import current_identity

_GATEWAY_LOCKS: dict[str, object] = {}
_LOCKS_GUARD = RLock()
_CALLER_ORIGIN = ContextVar("plugin_caller_origin", default=None)


@contextmanager
def caller_origin_scope(source: str):
    identity = current_identity()
    parent = _CALLER_ORIGIN.get()
    if identity.task_id or parent == "job":
        origin = "job"
    elif source == "desktop" and (identity.session_id or parent == "tool"):
        origin = "tool"
    else:
        origin = {"agent": "tool", "scheduler": "job", "desktop": "ui", "job": "job", "tool": "tool"}.get(source, "system")
    token = _CALLER_ORIGIN.set(origin)
    try:
        yield
    finally:
        _CALLER_ORIGIN.reset(token)


def current_caller_origin() -> str | None:
    return _CALLER_ORIGIN.get()


def plugin_user_id() -> str:
    return current_identity().user_id or os.environ.get("STELLA_PLUGIN_USER", "local-default")


def user_grant_ref(base: str, user_id: str | None = None) -> str:
    user = user_id or plugin_user_id()
    return base if user == "local-default" else f"{base}:{user}"


def serialized_gateway(function):
    with _LOCKS_GUARD:
        lock = _GATEWAY_LOCKS.setdefault(function.__module__, RLock())

    @wraps(function)
    def call(*args, **kwargs):
        with lock:
            return function(*args, **kwargs)
    return call
