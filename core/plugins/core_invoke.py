"""Reverse channel dispatch into a narrow list of existing public services."""
from datetime import datetime, timezone
import importlib

from core.plugins.caller import (delegation_scope, plugin_user_id, current_delegation, user_grant_ref, managed_plugin, current_consumer_plugin, current_invocation_purpose)
from core.plugins.contract import validate_operation_result
from core.plugins.lifecycle import DOMAINS, domain_data_handle
from models.plugin_service import invoke as invoke_model_service


def _domain_invoke(plugin_id, method, payload):
    if not managed_plugin(plugin_id, plugin_user_id()):
        raise PermissionError("target plugin is not installed")
    domain = DOMAINS[plugin_id]
    gateway = importlib.import_module(f'core.services.{domain}_gateway')
    session = getattr(gateway, f'ensure_{domain}_session')()
    contract = plugin_id + '@1'
    if (contract, method) not in session._method_permissions:
        raise PermissionError('public method is not declared')
    values = dict(payload)
    idempotency = values.pop('idempotencyKey', None)
    if session._method_effects[(contract, method)] != 'query' and not idempotency:
        raise PermissionError('delegated mutation requires a stable idempotency key')
    return session.invoke_contract(contract=contract, method=method, input_payload=values, origin='system',
        grant_ref=user_grant_ref(gateway._GRANT_REF),
        idempotency_key=idempotency, data_handle=domain_data_handle(plugin_id, plugin_user_id()))


PUBLIC_SERVICES = {plugin_id + '@1': (lambda method, payload, pid=plugin_id: _domain_invoke(pid, method, payload))
                   for plugin_id in DOMAINS}


PUBLIC_SERVICES['stella.models@1'] = invoke_model_service


def dispatch(session, params: dict, parent: dict) -> dict:
    required = {'contract', 'method', 'input', 'deadline', 'invocationRef'}
    if not isinstance(params, dict) or not required <= set(params) or set(params) - required - {'idempotencyKey'}:
        raise PermissionError('invalid CoreInvokeParams')
    context = parent.get('context') or {}
    if params['invocationRef'] != context.get('invocationRef') or context.get('userId') != session.user_id:
        raise PermissionError('callback invocationRef does not belong to this channel invocation')
    contract = params['contract']
    if contract not in PUBLIC_SERVICES:
        raise PermissionError('Core service is not public')
    chain = (current_delegation() or {}).get('chain') or context.get('delegationChain') or []
    target = contract.rsplit('@', 1)[0]
    if target == session.plugin_id or target in chain:
        raise PermissionError('cyclic plugin delegation')
    if not isinstance(params['method'], str) or not isinstance(params['input'], dict):
        raise PermissionError('invalid public method input')
    forbidden = {'userId', 'grantRef', 'context', 'dataHandle', '_hostDataHandle', 'dbPath', 'dataDir', 'origin', 'consumerPluginId'}
    if set(params['input']) & forbidden:
        raise PermissionError('callback cannot supply identity or data paths')
    deadline = min(datetime.fromisoformat(params['deadline'].replace('Z', '+00:00')),
                   datetime.fromisoformat(parent['deadline'].replace('Z', '+00:00')))
    if deadline.tzinfo is None or deadline <= datetime.now(timezone.utc):
        raise PermissionError('callback deadline expired')
    session.registry.require_generation(session.plugin_id, session.generation)
    if contract == 'stella.models@1':
        capability = 'models.chat' if params['method'] == 'complete' else 'models.embedding'
        parent_method = parent.get('method')
        declared = session._method_permissions.get((parent.get('contract'), parent_method), ())
        if capability not in declared:
            raise PermissionError('model capability not declared by invoking method')
        if managed_plugin(session.plugin_id, session.user_id):
            session.authz.check_scoped(grant_ref=context['grantRef'], plugin_id=session.plugin_id,
                user_id=session.user_id, consumer_plugin_id=current_consumer_plugin() or session.plugin_id, method=parent_method,
                required_capabilities=[capability], resources=[{'kind': 'user', 'id': session.user_id}],
                purpose='background' if context.get('origin') == 'job' or current_invocation_purpose() == 'background' else 'interactive')
        else:
            session.authz.check(grant_ref=context['grantRef'], plugin_id=session.plugin_id,
                user_id=session.user_id, required_capabilities=[capability], purpose='interactive',
                generation=session.generation, context_generation=session.generation)

    payload = dict(params['input'])
    if params.get('idempotencyKey'):
        payload['idempotencyKey'] = params['idempotencyKey']
    from common.runtime_identity import identity_scope, current_identity

    identity = current_identity()
    with identity_scope(user_id=session.user_id, agent_id=context.get('agentId') or identity.agent_id,
                        session_id=context.get('sessionId'), task_id=context.get('jobId') or identity.task_id,
                        run_id=context.get('runId') or identity.run_id):
        with delegation_scope(context, session.plugin_id, deadline):
            return validate_operation_result(PUBLIC_SERVICES[contract](params['method'], payload))
