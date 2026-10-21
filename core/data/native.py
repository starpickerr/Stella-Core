"""Authenticated Desktop scope selection; never accepts paths or authority."""
from contextlib import contextmanager

from common.runtime_identity import current_identity, identity_scope
from core.execution.context import current_execution_context, execution_scope


@contextmanager
def browse_scope(agent=None, session=None):
    active = current_execution_context()
    identity = current_identity()
    if active:
        if ((agent and agent != identity.agent_id) or (session and session != identity.session_id)):
            raise PermissionError('Data scope cannot replace bound execution identity')
        active.check_active()
        yield
        return
    from agent.registry import get_agent_registry
    profile = get_agent_registry().get(agent or identity.agent_id)
    with identity_scope(agent_id=profile.id, session_id=session or identity.session_id):
        with execution_scope(origin='ui'):
            yield


def scope_options():
    from agent.registry import get_agent_registry
    from agent.memory import get_conversation_store
    from core.workspace.service import WorkspaceService
    registry = get_agent_registry()
    identity = current_identity()
    profile = registry.get(identity.agent_id)
    context = WorkspaceService.context()
    store = get_conversation_store(profile.workspace)
    sessions = store.list_sessions(channel_type='web', page_size=200)['sessions']
    return {'scope': {'agent': profile.id, 'session': identity.session_id or '',
                      'kind': context.kind, 'root': str(context.root)},
            'agents': [{'id': row.id, 'name': row.name} for row in registry.list(include_disabled=False)],
            'workspaces': [{'session': row['session_id'], 'name': row.get('title') or row['session_id']}
                           for row in sessions]}
