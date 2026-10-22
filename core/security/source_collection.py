"""Narrow authority for Core's native Briefing source collection.

Installed owner defaults predate feature consumers. A native collection may
reuse exactly those read grants, with their live purpose/resource restrictions.
Plugin callbacks and explicit consumer policies never inherit this authority.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from core.plugins.caller import current_consumer_plugin, current_delegation, plugin_user_id, user_grant_ref

_COLLECTION_USER = ContextVar('native_briefing_source_user', default=None)
_READS = {
    ('stella.email', 'fetch_messages'): 'email.fetch',
    ('stella.elearning', 'fetch_source'): 'elearning.read',
    ('stella.calendar', 'list_events'): 'calendar.read',
}


@contextmanager
def briefing_source_collection():
    if current_delegation() or current_consumer_plugin() != 'stella.briefing':
        raise PermissionError('source collection requires the native Briefing caller')
    token = _COLLECTION_USER.set(plugin_user_id())
    try:
        yield
    finally:
        _COLLECTION_USER.reset(token)


def inherited_read_ref(*, grant_ref, plugin_id, user_id, consumer_plugin_id, method,
                       required_capabilities, purpose):
    capability = _READS.get((plugin_id, method))
    if (not capability or set(required_capabilities) != {capability}
            or purpose not in {'interactive', 'background'}
            or _COLLECTION_USER.get() != user_id or plugin_user_id() != user_id
            or consumer_plugin_id != 'stella.briefing'
            or current_consumer_plugin() != consumer_plugin_id or current_delegation()
            or grant_ref != user_grant_ref(plugin_id.removeprefix('stella.') + '-default-grant', user_id)):
        return None
    return f'{grant_ref}:{purpose}:{capability}'
