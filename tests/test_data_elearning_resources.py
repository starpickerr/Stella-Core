"""Data resources use the real eLearning MCP process with an isolated upstream."""
import pytest

from core.data.service import DataService, ProviderRegistry


@pytest.fixture
def integration(tmp_path, monkeypatch):
    from config import conf
    from agent.tools.tool_manager import ToolManager
    from tests.test_managed_mcp_domains import fake_config
    from core.data.elearning_provider import ElearningProvider
    monkeypatch.setenv('STELLA_MANAGED_MCP', '1')
    monkeypatch.setitem(conf(), 'agent_permission_mode', 'full-access')
    monkeypatch.setitem(conf(), 'security_policy', {'preset': 'full-access', 'rules': {}, 'connections': {}})
    manager = ToolManager()
    config = {**fake_config('elearning', tmp_path / 'elearning'),
              'agentTools': ['list_courses', 'fetch', 'list_files', 'sync_files'], 'settingsUrl': '/elearning'}
    config['args'][config['args'].index('--user-id') + 1] = 'local-default'
    monkeypatch.setattr(manager, '_load_mcp_configs', lambda: [config])
    was_enabled = manager._mcp_enabled(config)
    manager.set_mcp_enabled('elearning', True)
    manager.call_mcp_tool('elearning', 'save_settings', {'payload': {'enabled': True,
        'username': 'student', 'password': 'isolated-secret', 'courses': ['42']}}, host=True)
    registry = ProviderRegistry()
    registry.register('elearning', ElearningProvider(manager))
    service = DataService(tmp_path / 'data.db', registry)
    try:
        yield service, manager
    finally:
        manager.set_mcp_enabled('elearning', was_enabled)
        manager._teardown_mcp_server('elearning')


def test_real_elearning_resource_catalog_read_and_account_binding(integration):
    service, manager = integration
    source = service.discover()['sources'][0]
    assert source['provider'] == 'elearning' and 'isolated-secret' not in str(source)
    page = service.resources(source['id'])
    assert {'course', 'announcement', 'assignment', 'file'} <= {row['kind'] for row in page['resources']}
    for resource in page['resources']:
        assert service.read_resource(source['id'], resource['id'])['content']
    assert service.resources(source['id'], 'not found')['total'] == 0
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM records').fetchone()[0] == 0
    manager.call_mcp_tool('elearning', 'save_settings', {'payload': {'username': 'other-student',
        'password': 'other-secret', 'courses': ['42']}}, host=True)
    with pytest.raises(PermissionError, match='account'):
        service.read_resource(source['id'], page['resources'][0]['id'])


def test_elearning_live_connection_and_course_scope(integration, monkeypatch):
    from core.plugins.authz import PluginAuthorizationStore
    service, manager = integration
    source = service.discover()['sources'][0]
    resources = service.resources(source['id'])['resources']
    authz = PluginAuthorizationStore()
    monkeypatch.setattr('core.mcp.authorization.DEFAULT_AUTHZ', authz)
    for name, methods, scopes in [('metadata', ['get_settings', 'list_courses'], [{'kind': 'user', 'id': 'local-default'}]),
                                  ('course', ['fetch', 'list_files'], [{'kind': 'course', 'id': source['config']['account_id'] + ':42'}])]:
        authz.issue_scoped(grant_ref=name, parent_ref='elearning-default-grant', plugin_id='stella.elearning',
            user_id='local-default', consumer_plugin_id='stella.elearning', capability='elearning.read',
            methods=methods, resources=scopes, purpose='interactive')
    assignment = next(row for row in resources if row['kind'] == 'assignment')
    assert service.read_resource(source['id'], assignment['id'])['content']['payload']['body']
    authz.revoke('course')
    with pytest.raises(PermissionError):
        service.read_resource(source['id'], assignment['id'])
    manager.set_mcp_enabled('elearning', False)
    with pytest.raises(PermissionError):
        service.resources(source['id'])


def test_native_file_sync_uses_real_owner_and_preserves_modified_files(integration, tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as desktop
    from tests.test_data_api import call
    service, manager = integration
    from core.data.api import DataController
    monkeypatch.setattr('core.data.api.current_controller', lambda: DataController(service))
    monkeypatch.setattr(desktop, '_require_auth', lambda: None)
    monkeypatch.setattr(desktop.web, 'header', lambda *_: None)
    folder = tmp_path / 'downloads'
    folder.mkdir()
    manager.call_mcp_tool('elearning', 'save_file_sync_settings', {'root': str(folder)}, host=True)
    result = call(desktop.DataElearningSyncFilesHandler, body={'offset': 0, 'limit': 50})
    assert result['status'] == 'success' and result['sync']['processed'] == 1
    files = list(folder.rglob('*.pdf'))
    assert len(files) == 1 and files[0].read_bytes() == b'coursepdf'
    files[0].write_bytes(b'user changes')
    result = call(desktop.DataElearningSyncFilesHandler, body={'offset': 0, 'limit': 50})
    # An unchanged remote version is skipped by the existing owner, including
    # when its local copy was edited. It is not an upstream sync failure.
    assert result['status'] == 'success' and result['sync']['errors'] == []
    assert files[0].read_bytes() == b'user changes' and len(list(folder.rglob('*.pdf'))) == 1
    rejected = call(desktop.DataElearningSyncFilesHandler, body={'root': str(tmp_path / 'outside')})
    assert rejected['status'] == 'error' and not (tmp_path / 'outside').exists()
    manager.set_mcp_enabled('elearning', False)
    assert call(desktop.DataElearningSyncFilesHandler)['status'] == 'error'


def test_native_file_sync_respects_data_source_disable_and_revision(integration, tmp_path, monkeypatch):
    from core.data.api import DataController
    from channel.desktop import desktop_channel as desktop
    from tests.test_data_api import call
    service, manager = integration
    monkeypatch.setattr('core.data.api.current_controller', lambda: DataController(service))
    monkeypatch.setattr(desktop, '_require_auth', lambda: None)
    monkeypatch.setattr(desktop.web, 'header', lambda *_: None)
    folder = tmp_path / 'downloads'
    folder.mkdir()
    manager.call_mcp_tool('elearning', 'save_file_sync_settings', {'root': str(folder)}, host=True)
    source = service.discover()['sources'][0]
    service.configure_source(source['id'], enabled=False)
    denied = call(desktop.DataElearningSyncFilesHandler)
    assert denied['status'] == 'error' and not list(folder.rglob('*.pdf'))
    service.configure_source(source['id'], enabled=True)
    client = manager._mcp_registry._clients['elearning']
    original = client.call_tool_result

    def disable_after(method, *args, **kwargs):
        result = original(method, *args, **kwargs)
        if method == 'sync_files':
            service.configure_source(source['id'], enabled=False)
        return result

    monkeypatch.setattr(client, 'call_tool_result', disable_after)
    denied_result = call(desktop.DataElearningSyncFilesHandler)
    assert denied_result['status'] == 'error' and 'sync' not in denied_result


def test_mcp_result_rechecks_live_connection_permission(integration, monkeypatch):
    from config import conf
    _, manager = integration
    # Initialize the actual stdio worker, then revoke access after it replies.
    manager.call_mcp_tool('elearning', 'list_courses', {})
    client = manager._mcp_registry._clients['elearning']
    original = client.call_tool_result

    def revoke_after(method, *args, **kwargs):
        result = original(method, *args, **kwargs)
        if method == 'fetch':
            monkeypatch.setitem(conf(), 'security_policy', {'preset': 'full-access', 'rules': {},
                'connections': {'mcp:elearning': {'allowed': False}}})
        return result

    monkeypatch.setattr(client, 'call_tool_result', revoke_after)
    with pytest.raises(PermissionError, match='revoked'):
        manager.call_mcp_tool('elearning', 'fetch', {'since': '2026-09-01T00:00:00Z',
            'until': '2026-09-10T00:00:00Z', 'course_ids': ['42']})


def test_catalog_keeps_authorized_courses_and_methods_when_other_scopes_denied(integration, tmp_path, monkeypatch):
    from core.plugins.authz import PluginAuthorizationStore
    service, _ = integration
    (tmp_path / 'elearning/second-course').touch()
    source = service.discover()['sources'][0]
    authz = PluginAuthorizationStore()
    monkeypatch.setattr('core.mcp.authorization.DEFAULT_AUTHZ', authz)
    for name, methods, scopes in [('metadata', ['get_settings', 'list_courses'], [{'kind': 'user', 'id': 'local-default'}]),
                                  ('course', ['fetch'], [{'kind': 'course', 'id': source['config']['account_id'] + ':42'}])]:
        authz.issue_scoped(grant_ref=name, parent_ref='elearning-default-grant', plugin_id='stella.elearning',
            user_id='local-default', consumer_plugin_id='stella.elearning', capability='elearning.read',
            methods=methods, resources=scopes, purpose='interactive')
    page = service.resources(source['id'], kind='assignment')
    assert page['resources'] and all(row['kind'] == 'assignment' for row in page['resources'])
    assert all('42' in row['reference'] and '43' not in row['reference'] for row in page['resources'])
    assert service.resources(source['id'], kind='file')['total'] == 0
    assert service.read_resource(source['id'], page['resources'][0]['id'])['content']['payload']['body']


def test_mcp_honors_bound_execution_consumer_and_background_purpose(integration, monkeypatch):
    from core.plugins.authz import PluginAuthorizationStore
    from core.execution.context import execution_scope
    _, manager = integration
    manager.call_mcp_tool('elearning', 'list_courses', {})
    authz = PluginAuthorizationStore()
    monkeypatch.setattr('core.mcp.authorization.DEFAULT_AUTHZ', authz)
    authz.issue_scoped(grant_ref='owner-only', parent_ref='elearning-default-grant', plugin_id='stella.elearning',
        user_id='local-default', consumer_plugin_id='stella.elearning', capability='elearning.read',
        methods=['list_courses'], resources=[{'kind': 'user', 'id': 'local-default'}], purpose='interactive')
    assert manager.call_mcp_tool('elearning', 'list_courses', {})
    with execution_scope(origin='tool', consumer_plugin_id='third.party'), pytest.raises(PermissionError):
        manager.call_mcp_tool('elearning', 'list_courses', {})
    with execution_scope(origin='job'), pytest.raises(PermissionError):
        manager.call_mcp_tool('elearning', 'list_courses', {})
