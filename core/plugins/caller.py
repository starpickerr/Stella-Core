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


def issue_compatibility_grant(authz, **kwargs):
    """Only the opt-in legacy source path has an implicit compatibility grant.

    Installed/managed packages always require a separately approved grant.
    """
    from core.plugins.management import default_store

    if default_store().has_instance(kwargs['plugin_id'], kwargs['user_id']):
        return None
    return authz.issue(**kwargs)


def managed_plugin_route(plugin_id: str, environment_value: str) -> bool:
    from core.plugins.management import default_store

    return (default_store().has_instance(plugin_id, plugin_user_id()) or
            environment_value.strip().lower() in {"1", "true", "yes"})


@contextmanager
def managed_data_lease(plugin_id: str, *, mechanism: bool = False):
    from core.plugins.management import default_store
    from core.plugins.locks import package_lock

    store = default_store()
    user = plugin_user_id()
    if not store.has_instance(plugin_id, user):
        yield
        return

    def check():
        current = store.instance(plugin_id, user)
        if not mechanism and current['intent'] != 'enabled':
            raise PermissionError(f"plugin {current['intent']}: {plugin_id}")
        phase = store.runtime_state(plugin_id, user)
        if phase in {'maintenance', 'draining'}:
            raise PermissionError(f"plugin {phase}: {plugin_id}")

    check()
    with package_lock(store.root, plugin_id, exclusive=False):
        check()
        yield


def serialized_gateway(function):
    with _LOCKS_GUARD:
        lock = _GATEWAY_LOCKS.setdefault(function.__module__, RLock())

    @wraps(function)
    def call(*args, **kwargs):
        with lock:
            if function.__name__.startswith(("invoke_", "ensure_")):
                domain = function.__module__.rsplit('.', 1)[-1].removesuffix('_gateway')
                plugin_id = 'stella.' + {'todos': 'tasks'}.get(domain, domain)
                with managed_data_lease(plugin_id):
                    return function(*args, **kwargs)
            return function(*args, **kwargs)
    return call
