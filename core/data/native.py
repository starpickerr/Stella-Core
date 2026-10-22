"""Authenticated access to the user-global catalog, preserving the real caller."""
from contextlib import contextmanager

from core.execution.context import current_execution_context, execution_scope


@contextmanager
def native_data_access():
    active = current_execution_context()
    if active:
        active.check_active()
        yield
        return
    with execution_scope(origin='ui'):
        yield
