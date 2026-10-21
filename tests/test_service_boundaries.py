"""Trusted service boundaries preserve live authorization and private ownership."""
import threading

import pytest

from common.runtime_identity import identity_scope


@pytest.fixture
def work(tmp_path, monkeypatch):
    from agent.workspace import project_store
    monkeypatch.setattr('agent.workspace.context.personal_work_dir', lambda **_: tmp_path / 'work')
    monkeypatch.setattr(project_store, '_store_file', lambda: str(tmp_path / 'projects.json'))
    return tmp_path


def test_security_service_forces_background_and_rejects_identity_override(work, monkeypatch):
    from core.execution.context import execution_scope
    from core.security.service import SecurityService
    calls = []
    monkeypatch.setattr('agent.runtime.tool_invocation._permission_denial', lambda *args, **kwargs: calls.append(kwargs))
    with identity_scope(agent_id='alpha', session_id='output', task_id='daily'):
        with execution_scope():
            SecurityService.authorize_tool('read', {'path': 'report.txt'}, user_action=True)
            assert calls[-1]['noninteractive'] is True
            assert calls[-1]['user_action'] is False
            with pytest.raises(PermissionError):
                SecurityService.authorize_tool('read', {}, session_id='another-chat')


def test_tool_invocation_binds_execution_context(work):
    from agent.runtime.tool_invocation import invocation_scope
    from core.execution.context import current_execution_context
    with identity_scope(agent_id='alpha', session_id='chat'):
        with invocation_scope('call-1'):
            assert current_execution_context().identity.session_id == 'chat'
    assert current_execution_context() is None


def test_generic_private_plugin_handle_is_safe_and_legacy_handles_stay(work, monkeypatch):
    from core.plugins.storage import private_data_handle
    from core.plugins.lifecycle import domain_data_handle
    monkeypatch.setattr('common.state_dir.user_root', lambda *args, **_: work / 'user')
    handle = private_data_handle('org.example.plugin', 'alice', ensure=True)
    assert handle == {'namespace': 'org.example.plugin', 'dataDir': str(work / 'user/plugins/org.example.plugin')}
    assert domain_data_handle('org.example.plugin', 'alice') == handle
    assert domain_data_handle('stella.bills', 'alice')['dbPath'].endswith('/bills/bills.db')
    for name in ('../escape', 'stella/other', '', '..'):
        with pytest.raises(ValueError):
            private_data_handle(name, 'alice')
    (work / 'user/plugins/org.example.link').symlink_to(work)
    with pytest.raises(PermissionError):
        private_data_handle('org.example.link', 'alice')


def test_raw_private_plugin_data_is_protected(work, monkeypatch):
    from agent.tools.utils.credentials import is_credential_path
    monkeypatch.setattr('common.state_dir.briefing_db', lambda **_: work / 'user/briefing/briefing.db')
    assert is_credential_path(str(work / 'user/plugins/org.example.plugin/private.db'))
    assert is_credential_path(str(work / 'user/bills/bills.db-wal'))


def test_callback_cannot_supply_execution_authority_fields(work):
    from core.plugins.core_invoke import dispatch
    from types import SimpleNamespace
    session = SimpleNamespace(user_id='alice', plugin_id='stella.test')
    parent = {'context': {'invocationRef': 'ref', 'userId': 'alice'}, 'deadline': '2099-01-01T00:00:00Z'}
    for field in ('executionContext', 'workspaceId', 'agentId', 'sessionId', 'jobId', 'purpose', 'permissions'):
        with pytest.raises(PermissionError, match='identity|authority'):
            dispatch(session, {'contract': 'stella.models@1', 'method': 'complete', 'input': {field: 'forged'},
                               'invocationRef': 'ref', 'deadline': parent['deadline']}, parent)


def test_model_result_is_not_released_after_authorization_revocation(work, monkeypatch):
    from models import plugin_service
    from core.security.service import model_authorization_scope
    entered = threading.Event()
    finish = threading.Event()
    allowed = [True]
    def authorize():
        if not allowed[0]:
            raise PermissionError('model grant revoked')
    def invoke(*_):
        entered.set()
        finish.wait(1)
        return {'status': 'succeeded', 'sideEffects': 'none', 'value': 'private result'}
    monkeypatch.setattr(plugin_service, '_invoke', invoke)
    def revoke():
        entered.wait(1)
        allowed[0] = False
        finish.set()
    worker = threading.Thread(target=revoke)
    worker.start()
    try:
        with model_authorization_scope(authorize):
            with pytest.raises(PermissionError, match='revoked'):
                plugin_service.invoke('complete', {})
    finally:
        worker.join()


def test_callback_rejects_naive_deadline_as_permission_error(work, monkeypatch):
    from core.plugins.core_invoke import dispatch
    from types import SimpleNamespace
    session = SimpleNamespace(user_id='alice', plugin_id='stella.test')
    with pytest.raises(PermissionError, match='deadline'):
        dispatch(session, {'contract': 'stella.models@1', 'method': 'complete', 'input': {},
                           'invocationRef': 'ref', 'deadline': '2099-01-01T00:00:00'},
                 {'context': {'invocationRef': 'ref', 'userId': 'alice'}, 'deadline': '2099-01-01T00:00:00Z'})
