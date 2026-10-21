"""Live authorization orchestration, without another grant or policy store."""
from contextlib import contextmanager
from contextvars import ContextVar

_MODEL_AUTHORIZATION = ContextVar('stella_model_authorization', default=())


class SecurityService:
    @staticmethod
    def check_execution():
        from core.execution.context import current_execution_context
        from core.workspace.service import WorkspaceService
        context = current_execution_context()
        if context:
            context.check_active()
            WorkspaceService.context()
        return context

    @staticmethod
    def authorize_tool(tool_name, arguments, **kwargs):
        from agent.runtime.tool_invocation import _permission_denial
        context = SecurityService.check_execution()
        if context:
            for key in ('agent_id', 'session_id'):
                expected = getattr(context.identity, key)
                if kwargs.get(key) is not None and kwargs[key] != expected:
                    raise PermissionError('tool cannot replace execution identity')
            if context.origin != 'ui':
                kwargs['user_action'] = False
            if context.purpose == 'background':
                kwargs.update(noninteractive=True, user_action=False, wait_for_approval=False)
        reason = _permission_denial(tool_name, arguments, **kwargs)
        SecurityService.check_execution()
        return reason

    @staticmethod
    def authorize_model(session, parent, method):
        from core.plugins.caller import current_consumer_plugin, current_invocation_purpose, managed_plugin
        context = parent.get('context') or {}
        active = SecurityService.check_execution()
        session.registry.require_generation(session.plugin_id, session.generation)
        capability = {'complete': 'models.chat', 'embed': 'models.embedding',
                      'embedding_status': 'models.embedding'}.get(method)
        if capability is None:
            raise PermissionError('model method is not public')
        declared = session._method_permissions.get((parent.get('contract'), parent.get('method')), ())
        if capability not in declared:
            raise PermissionError('model capability not declared by invoking method')
        background = (context.get('origin') == 'job' or current_invocation_purpose() == 'background'
                      or active is not None and active.purpose == 'background')
        if managed_plugin(session.plugin_id, session.user_id):
            from core.plugins.caller import managed_data_lease
            with managed_data_lease(session.plugin_id, user_id=session.user_id):
                session.authz.check_scoped(grant_ref=context['grantRef'], plugin_id=session.plugin_id,
                    user_id=session.user_id, consumer_plugin_id=current_consumer_plugin() or session.plugin_id,
                    method=parent.get('method'), required_capabilities=[capability],
                    resources=[{'kind': 'user', 'id': session.user_id}],
                    purpose='background' if background else 'interactive')
        else:
            session.authz.check(grant_ref=context['grantRef'], plugin_id=session.plugin_id,
                user_id=session.user_id, required_capabilities=[capability],
                purpose='background' if background else 'interactive',
                generation=session.generation, context_generation=session.generation)

    @staticmethod
    def authorize_data(session, parent, source_id):
        from core.plugins.caller import current_consumer_plugin, current_invocation_purpose, managed_plugin
        context = parent.get('context') or {}
        method = parent.get('method')
        if 'data.read' not in session._method_permissions.get((parent.get('contract'), method), ()):
            raise PermissionError('data capability not declared by invoking method')
        if not isinstance(source_id, str) or not source_id:
            raise ValueError('source_id is required')
        session.registry.require_generation(session.plugin_id, session.generation)
        active = SecurityService.check_execution()
        background = (context.get('origin') == 'job' or current_invocation_purpose() == 'background'
                      or active is not None and active.purpose == 'background')
        if managed_plugin(session.plugin_id, session.user_id):
            session.authz.check_scoped(grant_ref=context['grantRef'], plugin_id=session.plugin_id,
                user_id=session.user_id, consumer_plugin_id=current_consumer_plugin() or session.plugin_id,
                method=method, required_capabilities=['data.read'], resources=[{'kind': 'data-source', 'id': source_id}],
                purpose='background' if background else 'interactive')
        else:
            session.authz.check(grant_ref=context['grantRef'], plugin_id=session.plugin_id,
                user_id=session.user_id, required_capabilities=['data.read'],
                purpose='background' if background else 'interactive',
                generation=session.generation, context_generation=session.generation)


def check_model_authorization():
    SecurityService.check_execution()
    for authorize in _MODEL_AUTHORIZATION.get():
        authorize()


@contextmanager
def model_authorization_scope(authorize):
    token = _MODEL_AUTHORIZATION.set((*_MODEL_AUTHORIZATION.get(), authorize))
    try:
        check_model_authorization()
        yield
    finally:
        _MODEL_AUTHORIZATION.reset(token)
