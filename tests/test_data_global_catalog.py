"""Data sources are user-global; execution workspaces are not data sources."""
import pytest

from common.runtime_identity import current_identity, identity_scope
from core.data.service import DataService, ProviderRegistry
from core.data.resources import Resource
from tests.test_data_resources import ReferenceProvider


def test_runtime_catalog_is_global_and_retires_old_workspace_references(tmp_path, monkeypatch):
    from core.data import runtime
    monkeypatch.setattr(runtime, 'data_service_db', lambda: tmp_path / 'data.db')
    monkeypatch.setattr('core.data.providers.McpProvider.discover', lambda _: [])
    monkeypatch.setattr('core.data.elearning_provider.ElearningProvider.discover', lambda _: [])
    monkeypatch.setattr('core.data.owned_providers.PluginResourceProvider.discover', lambda _: [])
    root = tmp_path / 'old-session'
    root.mkdir()
    note = root / 'note.txt'
    note.write_text('Keep the working file')
    with identity_scope(user_id='alice', agent_id='alpha', session_id='first'):
        service = runtime.current_service()
        legacy = {'id': 'workspace:old', 'name': 'session_old', 'kind': 'workspace',
                  'config': {'root': str(root)}, 'operations': ['metadata', 'configure', 'resources', 'read']}
        service.store.discover('workspace', legacy)
        resource = Resource.from_source(service.store.source('workspace:old'), 'note.txt', kind='file', name='note.txt')
        service.store.put_resources(service.store.source('workspace:old'), [resource])
        assert 'workspace' not in {row['id'] for row in service.providers.descriptors()}
        service.providers.register('documents', ReferenceProvider())
        first = service.discover()['sources']
        assert [row['id'] for row in first] == ['documents:library']
        with pytest.raises((PermissionError, RuntimeError)):
            service.read_resource('workspace:old', resource.id)
    with identity_scope(user_id='alice', agent_id='beta', session_id='second'):
        service = runtime.current_service()
        service.providers.register('documents', ReferenceProvider())
        assert service.discover()['sources'] == first
        assert service.resources('documents:library')['total'] == 1
    assert note.read_text() == 'Keep the working file'
    with identity_scope(user_id='bob'), pytest.raises(PermissionError, match='another user'):
        service.list_sources()


def test_native_data_ignores_legacy_scope_without_enumerating_conversations(tmp_path, monkeypatch):
    from channel.desktop import desktop_channel as desktop
    from core.data.api import DataController
    from core.execution.context import execution_scope, current_execution_context
    from tests.test_data_api import call
    registry = ProviderRegistry()
    registry.register('documents', ReferenceProvider())
    service = DataService(tmp_path / 'data.db', registry)
    controller = DataController(service)
    monkeypatch.setattr('core.data.api.current_controller', lambda: controller)
    monkeypatch.setattr('agent.memory.get_conversation_store', lambda *_: pytest.fail('Data enumerated conversations'))
    monkeypatch.setattr(desktop, '_require_auth', lambda: None)
    monkeypatch.setattr(desktop.web, 'header', lambda *_: None)
    expected = None
    for session in ['first', 'second']:
        with identity_scope(session_id=session):
            snapshot = call(desktop.DataManagementHandler, 'GET', params={'refresh': '1', 'storage': '0',
                            'agent': 'not-an-agent', 'session': 'unrelated-conversation'})
            assert snapshot['status'] == 'success'
            assert not {'scope', 'agents', 'workspaces'} & snapshot.keys()
            assert current_identity().session_id == session
            expected = expected or snapshot['sources']
            assert snapshot['sources'] == expected
    with identity_scope(session_id='bound'), execution_scope(origin='tool') as active:
        page = call(desktop.DataResourcesHandler, 'GET', params={'source_id': 'documents:library',
                    'agent': 'unrelated', 'session': 'unrelated'})
        assert page['status'] == 'success' and page['resources']
        assert current_execution_context() is active
        assert current_execution_context().origin == 'tool'
        assert current_identity().session_id == 'bound'
