"""Trusted caller identity and serialization for the single-user worker slots."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
import os
from threading import RLock

from common.runtime_identity import current_identity

_GATEWAY_LOCKS: dict[str, object] = {}
_LOCKS_GUARD = RLock()
_DELEGATION = ContextVar("approved_plugin_delegation", default=None)
_CONSUMER_PLUGIN = ContextVar("plugin_consumer", default=None)
_CALLER_ORIGIN = ContextVar("plugin_caller_origin", default=None)
_INVOCATION_DEADLINE = ContextVar("plugin_invocation_deadline", default=None)
_INVOCATION_PURPOSE = ContextVar("plugin_invocation_purpose", default=None)


@contextmanager
def invocation_purpose_scope(purpose):
    current = _INVOCATION_PURPOSE.get()
    token = _INVOCATION_PURPOSE.set('background' if current == 'background' else purpose)
    try:
        yield
    finally:
        _INVOCATION_PURPOSE.reset(token)


def current_invocation_purpose():
    from core.execution.context import current_execution_context
    active = current_execution_context()
    legacy = _INVOCATION_PURPOSE.get()
    if legacy == 'background' or active is not None and active.purpose == 'background':
        return 'background'
    return active.purpose if active is not None else legacy


def current_invocation_deadline():
    from core.execution.context import current_execution_context
    active = current_execution_context()
    candidates = [_INVOCATION_DEADLINE.get(), (_DELEGATION.get() or {}).get('deadline'),
                  active.deadline if active else None]
    return min((value for value in candidates if value is not None), default=None)


def remaining_invocation_seconds():
    from core.plugins.cancellation import check_cancelled
    check_cancelled()
    from core.execution.context import current_execution_context
    active = current_execution_context()
    if active:
        active.check_active()
    deadline = current_invocation_deadline()
    if deadline is None:
        return None
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise PermissionError('plugin invocation deadline expired')
    return remaining


@contextmanager
def invocation_budget(timeout_ms=30_000):
    deadline = datetime.now(timezone.utc) + timedelta(milliseconds=timeout_ms)
    parent = current_invocation_deadline()
    token = _INVOCATION_DEADLINE.set(min(deadline, parent) if parent else deadline)
    try:
        remaining_invocation_seconds()
        yield current_invocation_deadline()
    finally:
        _INVOCATION_DEADLINE.reset(token)


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
    from core.execution.context import current_execution_context
    active = current_execution_context()
    return active.origin if active is not None else _CALLER_ORIGIN.get()


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


@contextmanager
def gateway_invocation_scope(module_name):
    """Share a gateway's worker slot, admission lease and budget across adapters."""
    with _LOCKS_GUARD:
        lock = _GATEWAY_LOCKS.setdefault(module_name, RLock())
    with invocation_budget(), invocation_lock(lock):
        domain = module_name.rsplit('.', 1)[-1].removesuffix('_gateway')
        plugin_id = 'stella.' + {'todos': 'tasks'}.get(domain, domain)
        with managed_data_lease(plugin_id):
            yield


def serialized_gateway(function):
    with _LOCKS_GUARD:
        lock = _GATEWAY_LOCKS.setdefault(function.__module__, RLock())

    @wraps(function)
    def call(*args, **kwargs):
        if function.__name__.startswith(("invoke_", "ensure_")):
            with gateway_invocation_scope(function.__module__):
                return function(*args, **kwargs)
        with invocation_lock(lock, enforce_deadline=False):
            return function(*args, **kwargs)
    return call


def current_consumer_plugin() -> str | None:
    from core.execution.context import current_execution_context
    active = current_execution_context()
    legacy = _CONSUMER_PLUGIN.get()
    if active is not None and active.consumer_plugin_id:
        if legacy is not None and legacy != active.consumer_plugin_id:
            raise PermissionError('delegation consumer cannot replace execution consumer')
        return active.consumer_plugin_id
    return legacy


@contextmanager
def consumer_plugin_scope(plugin_id: str):
    """Core-owned delegation scope; never populated from a public request body."""
    parent = current_consumer_plugin()
    if parent is not None and parent != plugin_id:
        raise PermissionError('delegation consumer cannot be replaced')
    token = _CONSUMER_PLUGIN.set(plugin_id)
    try:
        yield
    finally:
        _CONSUMER_PLUGIN.reset(token)


def current_delegation() -> dict | None:
    return _DELEGATION.get()


@contextmanager
def delegation_scope(context: dict, caller_plugin: str, deadline):
    parent = _DELEGATION.get()
    if caller_plugin in (context.get('delegationChain') or []):
        raise PermissionError('cyclic plugin delegation')
    root_origin = parent['origin'] if parent else context['origin']
    if root_origin == 'plugin':
        raise PermissionError('delegation has no original caller')
    token = _DELEGATION.set({'context': context, 'callerPluginId': caller_plugin,
        'origin': root_origin, 'deadline': deadline,
        'purpose': 'background' if (root_origin == 'job' or _INVOCATION_PURPOSE.get() == 'background' or
                                    (parent or {}).get('purpose') == 'background') else 'interactive',
        'chain': [*(context.get('delegationChain') or []), caller_plugin]})
    origin_token = _CALLER_ORIGIN.set(root_origin)
    consumer_token = _CONSUMER_PLUGIN.set(current_consumer_plugin() or caller_plugin)
    try:
        yield
    finally:
        _CONSUMER_PLUGIN.reset(consumer_token)
        _CALLER_ORIGIN.reset(origin_token)
        _DELEGATION.reset(token)


@contextmanager
def invocation_lock(lock, *, enforce_deadline=True):
    """Delegated calls fail busy instead of creating a cross-worker lock cycle."""
    delegation = current_delegation()
    remaining = remaining_invocation_seconds() if enforce_deadline else None
    if delegation is not None:
        if not lock.acquire(blocking=False):
            raise PermissionError('public plugin service is busy; retry the operation')
    elif remaining is not None:
        while not lock.acquire(timeout=min(.05, remaining)):
            remaining = remaining_invocation_seconds()
    else:
        lock.acquire()
    try:
        if enforce_deadline:
            remaining_invocation_seconds()
        yield
    finally:
        lock.release()
