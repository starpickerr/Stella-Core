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


def test_agent_reads_global_sources_without_feature_selection_and_connection_can_revoke(integration, monkeypatch):
    from config import conf
    from common.runtime_identity import identity_scope
    from core.execution.context import execution_scope
    from core.data.usage import UsageService
    service, manager = integration
    source = service.discover()['sources'][0]
    # Feature consumption is separate from normal Agent access.
    UsageService(service).set('stella.briefing', source['id'], False)
    for session in ['first', 'second']:
        with identity_scope(session_id=session), execution_scope(origin='tool'):
            resources = service.resources(source['id'])['resources']
            assignment = next(row for row in resources if row['kind'] == 'assignment')
            assert service.read_resource(source['id'], assignment['id'])['content']
    monkeypatch.setitem(conf(), 'security_policy', {'preset': 'full-access', 'rules': {},
        'connections': {'mcp:elearning': {'allowed': False}}})
    with identity_scope(session_id='second'), execution_scope(origin='tool'):
        with pytest.raises(PermissionError):
            service.read_resource(source['id'], assignment['id'])
        with pytest.raises(PermissionError):
            manager.call_mcp_tool('elearning', 'list_courses', {})


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


@pytest.mark.parametrize('change', ['disable', 'restore', 'source_restore'])
def test_data_usage_activates_real_legacy_owner_and_controls_briefing(integration, monkeypatch, change):
    from core.data.usage import UsageService
    from core.data import runtime
    from core.services.elearning_facade import elearning_sources
    service, manager = integration
    monkeypatch.setattr(runtime, 'current_service', lambda: service)
    manager.call_mcp_tool('elearning', 'save_settings', {'payload': {'enabled': False}}, host=True)
    source = service.discover()['sources'][0]
    assert not elearning_sources()
    UsageService(service).set('stella.briefing', source['id'], True)
    sources = elearning_sources()
    assert len(sources) == 1
    # The old owner still gates fetch_source with its compatibility flag.
    assert manager.call_mcp_tool('elearning', 'get_settings', {}, host=True)['enabled']
    assert sources[0].fetch({}).items
    original_invoke = sources[0]._facade._invoke
    def disable_after_fetch(method, params, purpose=None):
        result = original_invoke(method, params, purpose)
        if method == 'fetch_source':
            if change == 'source_restore':
                service.configure_source(source['id'], enabled=False)
                service.configure_source(source['id'], enabled=True)
            else:
                UsageService(service).set('stella.briefing', source['id'], False)
                if change == 'restore':
                    UsageService(service).set('stella.briefing', source['id'], True)
        return result
    monkeypatch.setattr(sources[0]._facade, '_invoke', disable_after_fetch)
    with pytest.raises(PermissionError):
        sources[0].fetch({})
    UsageService(service).set('stella.briefing', source['id'], False)
    assert not elearning_sources()
    with pytest.raises(PermissionError):
        sources[0].fetch({})
    # Disabling one feature must not shut down the source for other consumers.
    assert service.resources(source['id'])['total'] > 0


def test_briefing_rediscovers_restored_elearning_without_data_page(integration, monkeypatch):
    from core.data import runtime
    from core.data.usage import UsageService
    from core.services.elearning_facade import elearning_sources
    service, _ = integration
    monkeypatch.setattr(runtime, 'current_service', lambda: service)
    source = service.discover()['sources'][0]
    UsageService(service).set('stella.briefing', source['id'], True)
    # A successful discovery while the owner is offline retires its presence.
    service.store.reconcile_presence('elearning', [])
    assert not service.store.source(source['id'])['present']
    assert elearning_sources()
    assert service.store.source(source['id'])['present']
    UsageService(service).set('stella.briefing', source['id'], False)
    assert not elearning_sources()


def test_native_briefing_elearning_keeps_background_course_scope_and_connection_policy(integration, monkeypatch):
    from types import SimpleNamespace
    from core.plugins.authz import PluginAuthorizationStore
    from core.services.elearning_facade import elearning_sources
    from core.data import runtime
    from core.data.usage import UsageService
    from agent.briefing.pipeline import BriefingPipeline
    from config import conf
    service, _ = integration
    monkeypatch.setattr(runtime, 'current_service', lambda: service)
    adapter = elearning_sources()[0]
    authz = PluginAuthorizationStore()
    monkeypatch.setattr('core.mcp.authorization.DEFAULT_AUTHZ', authz)
    ref = 'elearning-default-grant:background:elearning.read'
    authz.issue_scoped(grant_ref='elearning-default-grant:interactive:elearning.read',
        parent_ref='elearning-default-grant', plugin_id='stella.elearning', user_id='local-default',
        consumer_plugin_id='stella.elearning', capability='elearning.read', methods=['get_settings'],
        resources=[{'kind': 'user', 'id': 'local-default'}], purpose='interactive')
    authz.issue_scoped(grant_ref=ref, parent_ref='elearning-default-grant', plugin_id='stella.elearning',
        user_id='local-default', consumer_plugin_id='stella.elearning', capability='elearning.read',
        methods=['fetch_source'], resources=[{'kind': 'course', 'id': adapter.account_id + ':42'}], purpose='background')
    pipeline = BriefingPipeline(service=SimpleNamespace(get_cursor=lambda *args: None), generator=object())
    def collect():
        return pipeline._fetch_source(adapter, '2026-09-08T00:00:00Z', '2026-09-10T00:00:00Z')
    result = collect()
    assert result.items and {item.payload['course_id'] for item in result.items} == {'42'}
    authz.update_owned(ref, user_id='local-default', revision=1,
        resources=frozenset({'{"id":"other:43","kind":"course"}'}))
    with pytest.raises(PermissionError):
        collect()
    authz.update_owned(ref, user_id='local-default', revision=2,
        resources=frozenset({'{"id":"' + adapter.account_id + ':42","kind":"course"}'}))
    assert collect().items
    source = service.list_sources()[0]
    UsageService(service).set('stella.briefing', source['id'], False)
    with pytest.raises(PermissionError, match='usage'):
        collect()
    UsageService(service).set('stella.briefing', source['id'], True)
    monkeypatch.setitem(conf(), 'security_policy', {'preset': 'full-access', 'rules': {},
        'connections': {'mcp:elearning': {'allowed': False}}})
    with pytest.raises(PermissionError):
        collect()
