"""Cooperative cancellation reaches a real worker without corrupting its transport."""
import json
import threading
import time

import pytest
from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry


def package(path):
    path.mkdir()
    (path / 'plugin.json').write_text(json.dumps({'manifestVersion': 1, 'id': 'stella.sample.cancel', 'name': 'cancel',
        'version': '1.0.0', 'hostApi': '^1.0.0', 'runtime': {'kind': 'python', 'entry': 'main.py', 'abi': 'cp312'},
        'permissions': [{'capability': 'sample.read', 'required': True}], 'contributes': {'services': ['stella.sample.cancel@1']}}))
    (path / 'main.py').write_text('''from pathlib import Path
from stella_host import cancellation_token
SERVICE_DESCRIPTORS = [{'contract':'stella.sample.cancel@1','methods':[{'name':'run','effect':'query','permissions':['sample.read']}]}]
def handle_invoke(params):
    token = cancellation_token()
    if params['input'].get('wait'):
        Path(params['_hostDataHandle']['started']).touch()
        cancelled = token.wait(5)
    else:
        cancelled = token.is_set()
    return {'status':'succeeded','sideEffects':'none','value':{'cancelled':cancelled}}
''')
    return path


def test_cancel_reaches_active_worker_and_next_invocation_is_not_cancelled(tmp_path):
    from core.plugins.cancellation import cancellation_scope
    started = tmp_path / 'started'
    event = threading.Event()
    def stop():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not started.exists():
            time.sleep(.01)
        if started.exists():
            event.set()
    session = PluginSession(package(tmp_path / 'plugin'), source_label='test', registry=PluginRegistry())
    stopper = threading.Thread(target=stop)
    try:
        session.start()
        stopper.start()
        with cancellation_scope(event):
            result = session.invoke_contract(contract='stella.sample.cancel@1', method='run',
                input_payload={'wait': True}, origin='system', grant_ref='test', skip_authz=True,
                data_handle={'started': str(started)})
        assert result['status'] == 'cancelled'
        assert result['sideEffects'] == 'none'
        assert 'value' not in result  # A cancelled call must not release a successful payload.
        assert session.is_running
        result = session.invoke_contract(contract='stella.sample.cancel@1', method='run',
            input_payload={}, origin='system', grant_ref='test', skip_authz=True)
        assert result['value'] == {'cancelled': False}
    finally:
        if stopper.ident is not None:
            stopper.join(timeout=6)
        session.dispose()


def test_nested_scope_cannot_erase_cancellation():
    from core.plugins.cancellation import cancellation_scope, check_cancelled
    from agent.protocol.cancel import AgentCancelledError
    event = threading.Event()
    event.set()
    with cancellation_scope(event), cancellation_scope(None):
        with pytest.raises(AgentCancelledError):
            check_cancelled()
    check_cancelled()


def test_cancellation_interrupts_wait_for_a_busy_gateway_lock():
    from core.plugins.cancellation import cancellation_scope
    from core.plugins.caller import invocation_budget, invocation_lock
    from agent.protocol.cancel import AgentCancelledError
    lock = threading.Lock()
    lock.acquire()
    cancel, waiting = threading.Event(), threading.Event()
    outcome = []
    def request():
        try:
            with cancellation_scope(cancel), invocation_budget(3000):
                waiting.set()
                with invocation_lock(lock):
                    outcome.append('unexpected dispatch')
        except AgentCancelledError:
            outcome.append('cancelled')
    worker = threading.Thread(target=request)
    worker.start()
    try:
        assert waiting.wait(1)
        cancel.set()
        worker.join(timeout=.5)
        assert not worker.is_alive(), 'cancelled requests must not wait for another business invocation'
        assert outcome == ['cancelled']
    finally:
        lock.release()
        worker.join(timeout=4)
