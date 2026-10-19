"""Public stella_host module installed by the runner; no application imports."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import uuid

from core.plugins.protocol import make_request, read_frame, write_frame

_CURRENT = ContextVar('approved_plugin_invocation', default=None)
_input = None
_output = None


def configure(input_stream, output_stream):
    global _input, _output
    _input, _output = input_stream, output_stream


@contextmanager
def invocation_scope(params):
    token = _CURRENT.set(params)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def invoke(contract: str, method: str, input: dict, *, idempotency_key: str | None = None):
    parent = _CURRENT.get()
    if parent is None or _input is None or _output is None:
        raise PermissionError('core.invoke requires an active approved invocation')
    if datetime.fromisoformat(parent['deadline'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        raise PermissionError('invocation deadline expired')
    params = {'contract': contract, 'method': method, 'input': input, 'deadline': parent['deadline'],
              'invocationRef': parent['context']['invocationRef']}
    if idempotency_key is not None:
        params['idempotencyKey'] = idempotency_key
    request_id = uuid.uuid4().hex
    write_frame(_output, make_request('core.invoke', params, request_id))
    response = read_frame(_input)
    if response.get('id') != request_id or 'method' in response:
        raise RuntimeError('invalid Core callback response')
    if 'error' in response:
        error = response['error']
        if error.get('code') == -32001:
            raise PermissionError(error.get('message') or 'Core callback denied')
        raise RuntimeError(error.get('message') or 'Core service failed')
    return response['result']
