"""Reverse channel dispatch into a narrow list of existing public services."""
from contextlib import nullcontext
from datetime import datetime, timezone
import importlib

from core.plugins.caller import (delegation_scope, plugin_user_id, current_delegation, user_grant_ref, managed_plugin, current_consumer_plugin)
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


def _data_invoke(method, payload):
    from core.data.api import invoke_public
    return invoke_public(method, payload)


PUBLIC_SERVICES['stella.data@1'] = _data_invoke


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
    forbidden = {'userId', 'grantRef', 'context', 'dataHandle', '_hostDataHandle', 'dbPath', 'dataDir', 'origin', 'consumerPluginId',
                 'executionContext', 'workspaceId', 'agentId', 'sessionId', 'jobId', 'runId', 'purpose', 'permissions'}
    if set(params['input']) & forbidden:
        raise PermissionError('callback cannot supply identity or data paths')
    try:
        deadlines = [datetime.fromisoformat(value.replace('Z', '+00:00'))
                     for value in (params['deadline'], parent['deadline'])]
        if any(value.tzinfo is None for value in deadlines):
            raise ValueError('timezone required')
        deadline = min(deadlines)
    except (ValueError, TypeError, AttributeError) as exc:
        raise PermissionError('invalid callback deadline') from exc
    if deadline <= datetime.now(timezone.utc):
        raise PermissionError('callback deadline expired')
    session.registry.require_generation(session.plugin_id, session.generation)
    from core.security.service import SecurityService, model_authorization_scope
    if contract == 'stella.data@1':
        SecurityService.authorize_data(session, parent, params['input'].get('source_id'))
    if contract == 'stella.models@1':
        SecurityService.authorize_model(session, parent, params['method'])
    model_scope = (model_authorization_scope(lambda: SecurityService.authorize_model(session, parent, params['method']))
                   if contract == 'stella.models@1' else nullcontext())

    payload = dict(params['input'])
    if params.get('idempotencyKey'):
        payload['idempotencyKey'] = params['idempotencyKey']
    from common.runtime_identity import identity_scope, current_identity

    from core.execution.context import current_execution_context, execution_scope
    identity = current_identity()
    # The live Core scope outranks diagnostic worker metadata. Direct legacy
    # sessions establish identity once here, before constructing a Core scope.
    identity_context = (nullcontext() if current_execution_context() else
        identity_scope(user_id=session.user_id, agent_id=context.get('agentId') or identity.agent_id,
                       session_id=context.get('sessionId'), task_id=context.get('jobId') or identity.task_id,
                       run_id=context.get('runId') or identity.run_id))
    with identity_context, delegation_scope(context, session.plugin_id, deadline):
        with execution_scope(consumer_plugin_id=current_consumer_plugin(), deadline=deadline), model_scope:
            result = validate_operation_result(PUBLIC_SERVICES[contract](params['method'], payload))
            SecurityService.check_execution()
            if contract == 'stella.data@1':
                SecurityService.authorize_data(session, parent, params['input'].get('source_id'))
            return result
