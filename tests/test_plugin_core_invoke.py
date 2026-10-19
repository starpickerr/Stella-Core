"""Reverse requests run inside the real approved invocation and caller thread."""
import json
from pathlib import Path

import pytest

from core.plugins.host import PluginSession, PluginHostError
from core.plugins.registry import PluginRegistry


def _package(path: Path, *, forged=False):
    path.mkdir()
    (path / 'plugin.json').write_text(json.dumps({'manifestVersion': 1, 'id': 'stella.sample.callback', 'name': 'callback',
        'version': '1.0.0', 'hostApi': '^1.0.0', 'runtime': {'kind': 'python', 'entry': 'main.py', 'abi': 'cp312'},
        'permissions': [{'capability': 'sample.call', 'required': True}], 'contributes': {'services': ['stella.sample.callback@1']}}))
    (path / 'main.py').write_text('''from stella_host import invoke
SERVICE_DESCRIPTORS = [{'contract':'stella.sample.callback@1','methods':[{'name':'run','effect':'query','permissions':['sample.call']}]}]
def handle_invoke(params):
    return invoke('stella.sample.target@1', 'read', {'selected': 'source-1'})
''')
    if forged:
        source = (path / 'main.py').read_text().replace("    return invoke(", "    import stella_host\n    stella_host._CURRENT.set({**params, 'context': {**params['context'], 'invocationRef': 'forged'}})\n    return invoke(")
        (path / 'main.py').write_text(source)
    return path


def test_reverse_call_preserves_bound_consumer_original_identity_and_deadline(tmp_path, monkeypatch):
    from common.runtime_identity import identity_scope, current_identity
    from core.plugins import core_invoke
    from core.plugins.caller import current_caller_origin, current_consumer_plugin, current_delegation
    calls = []

    def target(method, payload):
        calls.append((method, payload, current_identity().user_id, current_caller_origin(), current_consumer_plugin(), current_delegation()))
        return {'status': 'succeeded', 'sideEffects': 'none', 'value': {'called': True}}

    monkeypatch.setitem(core_invoke.PUBLIC_SERVICES, 'stella.sample.target@1', target)
    with identity_scope(user_id='alice', session_id='session-1'):
        session = PluginSession(_package(tmp_path / 'callback'), source_label='test', registry=PluginRegistry(), user_id='alice')
        monkeypatch.setattr('core.plugins.host._conversation_permission_denial', lambda **kwargs: None)
        try:
            session.start()
            result = session.invoke('run')
            assert result['value']['called']
            assert calls[0][:5] == ('read', {'selected': 'source-1'}, 'alice', 'tool', 'stella.sample.callback')
            assert calls[0][5]['context']['sessionId'] == 'session-1'
        finally:
            session.dispose()


def test_forged_reverse_invocation_and_management_contract_are_rejected(tmp_path):
    from core.plugins.core_invoke import dispatch
    session = PluginSession(_package(tmp_path / 'callback'), source_label='test', registry=PluginRegistry())
    context = {'invocationRef': 'actual', 'userId': session.user_id}
    with pytest.raises(PermissionError):
        dispatch(session, {'contract':'core.management@1','method':'approve','input':{},'invocationRef':'forged',
            'deadline':'2099-01-01T00:00:00Z'}, {'context':context, 'deadline':'2099-01-01T00:00:00Z'})
    with pytest.raises(PermissionError):
        dispatch(session, {'contract':'core.management@1','method':'approve','input':{},'invocationRef':'actual',
            'deadline':'2099-01-01T00:00:00Z'}, {'context':context, 'deadline':'2099-01-01T00:00:00Z'})


def test_forged_invocation_is_rejected_over_the_real_reverse_channel(tmp_path, monkeypatch):
    from core.plugins import core_invoke
    calls = []
    monkeypatch.setitem(core_invoke.PUBLIC_SERVICES, 'stella.sample.target@1', lambda *_: calls.append(True))
    session = PluginSession(_package(tmp_path / 'forged', forged=True), source_label='test', registry=PluginRegistry())
    try:
        session.start()
        with pytest.raises(PluginHostError, match='invocationRef'):
            session.invoke('run')
        assert not calls
    finally:
        session.dispose()


def test_direct_host_session_still_restores_its_bound_user_for_callback(tmp_path, monkeypatch):
    from common.runtime_identity import current_identity
    from core.plugins import core_invoke
    seen = []
    monkeypatch.setitem(core_invoke.PUBLIC_SERVICES, 'stella.sample.target@1',
        lambda *_: {'status':'succeeded','sideEffects':'none','value':seen.append(current_identity().user_id)})
    session = PluginSession(_package(tmp_path / 'bound-user'), source_label='test', registry=PluginRegistry(), user_id='alice')
    try:
        session.start()
        session.invoke('run')
        assert seen == ['alice']
    finally:
        session.dispose()


def test_worker_startup_shares_the_parent_deadline(tmp_path):
    from datetime import datetime, timedelta, timezone
    from core.plugins.caller import delegation_scope

    package = _package(tmp_path / 'slow-start')
    entry = package / 'main.py'
    entry.write_text('import time\ntime.sleep(0.5)\n' + entry.read_text())
    session = PluginSession(package, source_label='test', registry=PluginRegistry())
    try:
        with delegation_scope({'origin': 'ui'}, 'stella.briefing',
                              datetime.now(timezone.utc) + timedelta(milliseconds=100)):
            with pytest.raises((PluginHostError, PermissionError), match='timed out|deadline expired'):
                session.start()
        assert session._proc is None
        assert session.registry.get(session.plugin_id) is None
    finally:
        session.dispose()


def test_package_lease_cannot_outlive_the_invocation_deadline(tmp_path):
    from core.plugins.caller import invocation_budget
    from core.plugins.locks import package_lock

    with package_lock(tmp_path, 'busy-plugin', exclusive=True):
        with invocation_budget(30):
            with pytest.raises(PermissionError, match='deadline expired'):
                with package_lock(tmp_path, 'busy-plugin', exclusive=False):
                    pytest.fail('busy package was admitted')
