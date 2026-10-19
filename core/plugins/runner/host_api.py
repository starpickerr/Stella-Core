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


class CancellationToken:
    """Read-only cancellation for the currently approved invocation."""
    def __init__(self, params):
        self._path = (params.get('_hostDataHandle') or {}).get('cancellationPath')
        self._deadline = datetime.fromisoformat(params['deadline'].replace('Z', '+00:00'))

    def is_set(self):
        if datetime.now(timezone.utc) >= self._deadline:
            return True
        if self._path:
            from pathlib import Path
            try:
                return Path(self._path).read_bytes() == b'1'
            except OSError:
                return True
        return False

    def wait(self, timeout=None):
        import time
        end = None if timeout is None else time.monotonic() + max(0, timeout)
        while not self.is_set():
            if end is not None and time.monotonic() >= end:
                return False
            time.sleep(.02 if end is None else min(.02, max(0, end - time.monotonic())))
        return True


def cancellation_token():
    params = _CURRENT.get()
    if params is None:
        raise PermissionError('cancellation token requires an active approved invocation')
    return CancellationToken(params)
