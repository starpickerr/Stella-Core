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


def test_tool_context_cannot_claim_native_user_action(work, monkeypatch):
    from core.execution.context import execution_scope
    from core.security.service import SecurityService
    calls = []
    monkeypatch.setattr('agent.runtime.tool_invocation._permission_denial', lambda *args, **kwargs: calls.append(kwargs))
    with identity_scope(agent_id='alpha', session_id='chat'):
        with execution_scope(origin='tool'):
            SecurityService.authorize_tool('read', {'path': 'note.txt'}, user_action=True)
    assert calls[-1]['user_action'] is False


def test_execution_deadline_is_the_actual_plugin_budget(work):
    from core.execution.context import execution_scope
    from core.plugins.caller import invocation_budget, current_invocation_deadline, remaining_invocation_seconds
    from datetime import datetime, timedelta, timezone
    with identity_scope(agent_id='alpha', session_id='chat'):
        deadline = datetime.now(timezone.utc) + timedelta(seconds=1)
        with invocation_budget(30_000), execution_scope(deadline=deadline):
            assert current_invocation_deadline() == deadline
            assert 0 < remaining_invocation_seconds() <= 1


def test_plugin_ui_origin_cannot_hide_background_scope(work, monkeypatch):
    from pathlib import Path
    from core.execution.context import execution_scope
    from core.plugins.authz import PluginAuthorizationStore
    from core.plugins.host import PluginSession
    from core.plugins.registry import PluginRegistry
    authz = PluginAuthorizationStore()
    session = PluginSession(Path('samples/plugins/alpha'), source_label='test', registry=PluginRegistry(), authz=authz)
    authz.issue(grant_ref='interactive-only', plugin_id=session.plugin_id, user_id=session.user_id,
                capabilities=['sample.ping'], purposes=['interactive'])
    monkeypatch.setattr('core.plugins.host._conversation_permission_denial', lambda **_: 'background denied')
    try:
        session.start()
        with identity_scope(agent_id='alpha', session_id='output', task_id='daily'), execution_scope():
            with pytest.raises(PermissionError, match='purpose|background'):
                session.invoke_contract(contract='stella.sample.alpha@1', method='ping', input_payload={},
                                        origin='ui', grant_ref='interactive-only')
    finally:
        session.dispose()


def test_plugin_storage_rejects_symlink_in_user_root_parent(work, monkeypatch):
    from core.plugins.storage import private_data_handle
    shared = work / 'shared'
    shared.mkdir()
    outside = work / 'outside'
    outside.mkdir()
    (shared / 'users').symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr('common.state_dir.shared_root', lambda: shared)
    monkeypatch.setattr('common.state_dir.user_root', lambda *args, **_: shared / 'users/alice')
    with pytest.raises(PermissionError, match='symlink'):
        private_data_handle('org.example.plugin', 'alice', ensure=True)
    assert not (outside / 'alice').exists()


def test_full_access_cannot_read_legacy_briefing_or_automation_databases(work, monkeypatch):
    from agent.permission.gateway import SecurityGateway, Scope
    monkeypatch.setattr('common.state_dir.briefing_db', lambda **_: work / 'user/briefing/briefing.db')
    monkeypatch.setattr('common.state_dir.scheduler_file', lambda **_: work / 'state/scheduler/tasks.json')
    monkeypatch.setattr('common.state_dir.state_root', lambda *args, **_: work / 'state')
    monkeypatch.setattr('common.state_dir.shared_root', lambda: work / 'state')
    for db in (work / 'user/briefing/briefing.db', work / 'state/scheduler/automation.db'):
        for suffix in ('', '-wal', '-shm', '-journal'):
            path = str(db) + suffix
            decision = SecurityGateway.check('full-access', 'read', {'path': path}, cwd=str(work),
                                             scope=Scope(write_roots=(str(work),)))
            assert not decision.allowed, path


def test_task_private_root_cannot_alias_source_conversation(work):
    from core.workspace.service import WorkspaceService
    from agent.workspace.context import resolve_context
    source = resolve_context('source', 'alpha', ensure=True)
    (source.root / 'secret.txt').write_text('source private')
    task = work / 'work/automations/alpha/daily'
    task.parent.mkdir(parents=True)
    task.symlink_to(source.root, target_is_directory=True)
    with identity_scope(agent_id='alpha', session_id='source', task_id='daily'):
        with pytest.raises(PermissionError, match='symlink'):
            WorkspaceService.context()


def test_native_adapter_observes_host_execution_origin(work):
    from core.execution.context import execution_scope
    from core.mcp.managed import native_user_action
    with identity_scope(agent_id='alpha', session_id='chat'), execution_scope(origin='tool'):
        assert native_user_action(True, 'list_courses', 'interactive') is False
