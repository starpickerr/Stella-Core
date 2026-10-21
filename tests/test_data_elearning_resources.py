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
