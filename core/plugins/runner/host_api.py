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


def _mutate_receipt(params, operation):
    """Durable generic receipts; never replay a write whose outcome is unknown."""
    import hashlib
    import json
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    key = params.get('idempotencyKey')
    if not key:
        raise ValueError('mutation requires an idempotency key')
    handle = params.get('_hostDataHandle') or {}
    root = Path(handle['dataDir'])
    root.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps({'method': params['method'], 'input': params['input']},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with closing(sqlite3.connect(root / '.operations.sqlite')) as db:
        db.execute('CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT)')
        row = db.execute('SELECT fingerprint,result FROM receipts WHERE id=?', (key,)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise ValueError('idempotency key reused with different input')
            if row[1] is None:
                return {'status': 'unknown', 'sideEffects': 'unknown', 'operationId': key}
            return json.loads(row[1])
        with db:
            db.execute('INSERT INTO receipts VALUES (?,?,NULL)', (key, fingerprint))
        result = operation(params)
        result['operationId'] = key
        with db:
            db.execute('UPDATE receipts SET result=? WHERE id=?', (json.dumps(result), key))
        return result



def mutate(params, operation):
    """Serialize the entire read/check/write transaction across worker processes."""
    from pathlib import Path
    from core.plugins.locks import package_lock
    root = Path((params.get('_hostDataHandle') or {})['dataDir'])
    deadline = datetime.fromisoformat(params['deadline'].replace('Z', '+00:00'))
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise PermissionError('mutation deadline expired')
    with package_lock(root / '.stella-runtime', 'domain-writes', exclusive=True, timeout=min(10, remaining)):
        if CancellationToken(params).is_set():
            raise PermissionError('mutation cancelled or expired')
        return _mutate_receipt(params, operation)
