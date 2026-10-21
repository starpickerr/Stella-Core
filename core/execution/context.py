"""Immutable, host-owned execution scope; carries constraints, never an ACL.

Only Core constructs these values. Wire payloads are diagnostic descriptions,
not credentials. Every operation still checks the current Security policy.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from common.runtime_identity import RuntimeIdentity, current_identity
from agent.workspace.context import WorkContext

_CURRENT = ContextVar('stella_execution_context', default=None)
_ORIGINS = frozenset({'ui', 'tool', 'job', 'system'})


@dataclass(frozen=True)
class ExecutionContext:
    identity: RuntimeIdentity
    workspace: WorkContext
    origin: str
    purpose: str
    consumer_plugin_id: str | None = None
    deadline: datetime | None = None

    def check_active(self):
        if current_identity() != self.identity:
            raise PermissionError('execution identity changed')
        if self.origin not in _ORIGINS or self.purpose not in {'interactive', 'background'}:
            raise PermissionError('invalid execution origin or purpose')
        if (self.identity.task_id or self.origin == 'job') and self.purpose != 'background':
            raise PermissionError('background execution cannot become interactive')
        if self.deadline is not None:
            if self.deadline.tzinfo is None:
                raise PermissionError('execution deadline requires timezone')
            if self.deadline <= datetime.now(timezone.utc):
                raise PermissionError('execution deadline expired')
        from core.plugins.cancellation import check_cancelled
        check_cancelled()


def current_execution_context() -> ExecutionContext | None:
    return _CURRENT.get()


def capture_execution_context(*, origin=None, consumer_plugin_id=None, deadline=None):
    parent = current_execution_context()
    if parent is not None:
        parent.check_active()
        # Derivation may add a consumer and shorten a deadline, never replace
        # the original principal, caller origin or workspace.
        if origin is not None and origin != parent.origin:
            raise PermissionError('execution origin cannot be replaced')
        if parent.consumer_plugin_id and consumer_plugin_id not in (None, parent.consumer_plugin_id):
            raise PermissionError('execution consumer cannot be replaced')
        return replace(parent, consumer_plugin_id=parent.consumer_plugin_id or consumer_plugin_id,
                       deadline=min(parent.deadline, deadline) if parent.deadline and deadline else parent.deadline or deadline)
    from core.workspace.service import WorkspaceService
    identity = current_identity()
    origin = 'job' if identity.task_id else origin or ('tool' if identity.session_id else 'system')
    return ExecutionContext(identity, WorkspaceService.context(), origin,
                            'background' if origin == 'job' else 'interactive', consumer_plugin_id, deadline)


@contextmanager
def execution_scope(context=None, **constraints):
    parent = current_execution_context()
    context = context if context is not None else capture_execution_context(**constraints)
    context.check_active()
    if parent is not None:
        parent.check_active()
        if (context.identity != parent.identity or context.workspace != parent.workspace
                or context.origin != parent.origin
                or (parent.purpose == 'background' and context.purpose != 'background')
                or (parent.consumer_plugin_id and context.consumer_plugin_id != parent.consumer_plugin_id)
                or (parent.deadline and (context.deadline is None or context.deadline > parent.deadline))):
            raise PermissionError('nested execution context cannot broaden its parent')
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
