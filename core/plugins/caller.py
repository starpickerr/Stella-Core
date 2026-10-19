"""Trusted caller identity and serialization for the single-user worker slots."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import os
from threading import RLock

from common.runtime_identity import current_identity

_GATEWAY_LOCKS: dict[str, object] = {}
_LOCKS_GUARD = RLock()
_CONSUMER_PLUGIN = ContextVar("plugin_consumer", default=None)
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


def managed_plugin(plugin_id: str, user_id: str) -> bool:
    from core.plugins.management import default_store

    store = default_store()
    # An installed package never regains legacy behavior for a new user or
    # when its selection is corrupt. Enrollment and migration are explicit.
    return (store.has_instance(plugin_id, user_id) or
            (store.root / 'packages' / plugin_id / 'current.json').exists())


def issue_compatibility_grant(authz, **kwargs):
    """Only the opt-in legacy source path has an implicit compatibility grant.

    Installed/managed packages always require a separately approved grant.
    """
    if managed_plugin(kwargs['plugin_id'], kwargs['user_id']):
        return None
    return authz.issue(**kwargs)


def managed_plugin_route(plugin_id: str, environment_value: str) -> bool:
    return (managed_plugin(plugin_id, plugin_user_id()) or
            environment_value.strip().lower() in {"1", "true", "yes"})


@contextmanager
def managed_data_lease(plugin_id: str, *, mechanism: bool = False, user_id: str | None = None):
    from core.plugins.management import default_store
    from core.plugins.locks import package_lock

    store = default_store()
    user = user_id or plugin_user_id()
    if not managed_plugin(plugin_id, user):
        yield
        return
    if not store.has_instance(plugin_id, user):
        raise PermissionError('user is not enrolled; enable the plugin to migrate user data')

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


def current_consumer_plugin() -> str | None:
    return _CONSUMER_PLUGIN.get()


@contextmanager
def consumer_plugin_scope(plugin_id: str):
    """Core-owned delegation scope; never populated from a public request body."""
    parent = _CONSUMER_PLUGIN.get()
    if parent is not None and parent != plugin_id:
        raise PermissionError('delegation consumer cannot be replaced')
    token = _CONSUMER_PLUGIN.set(plugin_id)
    try:
        yield
    finally:
        _CONSUMER_PLUGIN.reset(token)
