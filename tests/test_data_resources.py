"""Provider/Source/Resource references are owner-backed and never confer access."""
from dataclasses import replace
import pytest

from common.runtime_identity import identity_scope
from core.data.service import DataService, ProviderRegistry
from tests.test_data_service import Provider as CollectingProvider


class ReferenceProvider:
    def __init__(self):
        self.allowed = True
        self.after_read = lambda: None
        self.content = 'owner data'

    def discover(self):
        return [{'id': 'documents:library', 'name': 'Documents', 'kind': 'document',
                 'operations': ['metadata', 'configure', 'resources', 'read'], 'config': {}}]

    def authorize(self, source, operation):
        if not self.allowed:
            raise PermissionError('owner access revoked')

    def resource(self, source):
        from core.data.resources import Resource
        return Resource.from_source(source, 'doc:42', kind='document', name='Notes')

    def resources(self, source, query, limit, offset):
        rows = [self.resource(source)] if not query or query in 'Notes' else []
        return {'resources': rows[offset:offset + limit], 'total': len(rows)}

    def read_resource(self, source, resource):
        item = self.resource(source)
        if resource.id != item.id:
            raise KeyError('resource not found')
        self.after_read()
        return {'resource': item, 'content': self.content}


@pytest.fixture
def env(tmp_path):
    registry = ProviderRegistry()
    owner = ReferenceProvider()
    registry.register('documents', owner)
    service = DataService(tmp_path / 'data.db', registry)
    service.discover()
    return service, owner


def test_reference_provider_has_no_fake_account_and_stable_provenance(env):
    service, owner = env
    assert 'account_id' not in service.list_sources()[0]
    first = service.resources('documents:library')['resources'][0]
    service.discover()
    assert first == service.resources('documents:library')['resources'][0]
    assert first['source_id'] == 'documents:library' and first['provider'] == 'documents'
    assert first['reference'] == 'doc:42' and 'content' not in first
    assert service.read_resource('documents:library', first['id'])['content'] == 'owner data'
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM records').fetchone()[0] == 0


def test_reference_source_declares_real_operations_and_no_collection_side_effects(env):
    service, _ = env
    for operation in (lambda: service.sync('documents:library'),
                      lambda: service.subscribe('documents:library', 'consumer'),
                      lambda: service.configure_source('documents:library', storage='persistent')):
        with pytest.raises(ValueError, match='support'):
            operation()
    assert service.sync_state('documents:library')['running'] is False


def test_reference_read_rechecks_owner_and_source_revision(env):
    service, owner = env
    identifier = service.resources('documents:library')['resources'][0]['id']
    owner.after_read = lambda: setattr(owner, 'allowed', False)
    with pytest.raises(PermissionError, match='revoked'):
        service.read_resource('documents:library', identifier)
    owner.allowed = True
    owner.after_read = lambda: service.configure_source('documents:library', enabled=False)
    with pytest.raises(PermissionError, match='disabled|changed'):
        service.read_resource('documents:library', identifier)


def test_provider_cannot_forge_resource_identity_or_release_cross_source_content(env):
    service, owner = env
    original = owner.resource
    service.resources('documents:library')
    owner.resource = lambda source: replace(original(source), source_id='other-source')
    with pytest.raises(ValueError, match='identity'):
        service.resources('documents:library')
    with pytest.raises(ValueError, match='identity'):
        service.read_resource('documents:library', original(service.store.source('documents:library')).id)


def test_legacy_collected_records_are_resources_without_identity_or_content_migration(tmp_path):
    registry = ProviderRegistry()
    registry.register('messages', CollectingProvider())
    service = DataService(tmp_path / 'data.db', registry)
    service.discover()
    record = service.sync('messages:a')['records'][0]
    resource = service.resources('messages:a')['resources'][0]
    assert resource['reference'] == record['id']
    assert service.read_resource('messages:a', resource['id'])['content'] == record['item']
    assert service.query('messages:a')['records'][0]['id'] == record['id']


def test_failed_discovery_is_atomic_and_cannot_claim_another_providers_source(tmp_path):
    registry = ProviderRegistry()
    registry.register('messages', CollectingProvider())
    service = DataService(tmp_path / 'data.db', registry)
    service.discover()
    owner = ReferenceProvider()
    owner.discover = lambda: [{'id': 'new', 'name': 'Valid', 'kind': 'file'},
                             {'id': 'messages:a', 'name': 'Hijacked', 'kind': 'file'}]
    registry.register('documents', owner)
    with pytest.raises(ValueError):
        service.discover()
    assert [row['id'] for row in service.list_sources()] == ['messages:a']


def test_workspace_resources_follow_scope_and_do_not_expose_private_storage(tmp_path, monkeypatch):
    from core.data.workspace_provider import WorkspaceProvider
    from agent.workspace import project_store
    from agent.registry import AgentRegistry
    registry = AgentRegistry.from_config({'default_agent_id': 'alpha', 'agents': [
        {'id': 'alpha', 'name': 'Alpha', 'workspace': str(tmp_path / 'state')}]})
    monkeypatch.setattr('agent.registry.get_agent_registry', lambda selected=registry: selected)
    work = tmp_path / 'work'
    monkeypatch.setattr('agent.workspace.context.personal_work_dir', lambda **_: work)
    monkeypatch.setattr(project_store, '_store_file', lambda: str(tmp_path / 'projects.json'))
    with identity_scope(agent_id='alpha', session_id='chat', user_id='alice'):
        root = work / 'sessions/alpha/chat'
        root.mkdir(parents=True)
        (root / 'notes.txt').write_text('local note')
        protected = tmp_path / 'user/plugins/private'
        protected.mkdir(parents=True)
        (protected / 'secret.txt').write_text('secret')
        (root / 'private').symlink_to(protected, target_is_directory=True)
        monkeypatch.setattr('agent.tools.utils.credentials.protected_credential_folders', lambda: {str(protected)})
        registry = ProviderRegistry()
        registry.register('workspace', WorkspaceProvider())
        service = DataService(tmp_path / 'data.db', registry)
        service.discover()
        source_id = service.list_sources()[0]['id']
        page = service.resources(source_id)
        assert [row['name'] for row in page['resources']] == ['notes.txt']
        assert service.read_resource(source_id, page['resources'][0]['id'])['content'] == 'local note'
        with identity_scope(session_id='another'):
            assert service.list_sources() == []
            with pytest.raises(PermissionError):
                service.read_resource(source_id, page['resources'][0]['id'])


def test_workspace_and_record_resource_apis_require_auth_and_live_owner(env, monkeypatch):
    from tests.test_data_api import call
    from channel.desktop import desktop_channel as desktop
    from core.data.api import DataController
    service, owner = env
    monkeypatch.setattr('core.data.api.current_controller', lambda: DataController(service))
    calls = []
    monkeypatch.setattr(desktop, '_require_auth', lambda: calls.append(True))
    monkeypatch.setattr(desktop.web, 'header', lambda *args: None)
    page = call(desktop.DataResourcesHandler, 'GET', params={'source_id': 'documents:library'})
    assert page['status'] == 'success'
    identifier = page['resources'][0]['id']
    owner.allowed = False
    denied = call(desktop.DataResourcesHandler, 'GET', params={'source_id': 'documents:library', 'resource_id': identifier})
    assert denied['status'] == 'error' and 'content' not in denied
    assert len(calls) == 2


def test_real_plugin_callback_consumes_resources_and_rechecks_its_grant(env, tmp_path, monkeypatch):
    import json
    from core.data.api import DataController
    from core.plugins.host import PluginSession, PluginHostError
    from core.plugins.registry import PluginRegistry
    from core.plugins.authz import PluginAuthorizationStore
    service, owner = env
    monkeypatch.setattr('core.data.api.current_controller', lambda: DataController(service))
    package = tmp_path / 'consumer'
    package.mkdir()
    (package / 'plugin.json').write_text(json.dumps({
        'manifestVersion': 1, 'id': 'sample.consumer', 'name': 'Consumer', 'version': '1.0.0', 'hostApi': '^1.0.0',
        'runtime': {'kind': 'python', 'entry': 'main.py', 'abi': 'cp312'},
        'permissions': [{'capability': 'data.read', 'required': True}],
        'contributes': {'services': ['sample.consumer@1']}}))
    (package / 'main.py').write_text("""from stella_host import invoke
SERVICE_DESCRIPTORS = [{'contract': 'sample.consumer@1', 'methods': [{'name': 'run', 'effect': 'query', 'permissions': ['data.read']}]}]
def handle_invoke(params):
    return invoke('stella.data@1', 'resources', {'source_id': 'documents:library'})
""")
    authz = PluginAuthorizationStore()
    session = PluginSession(package, source_label='test', registry=PluginRegistry(), authz=authz)
    try:
        session.start()
        assert session.invoke('run')['value']['resources'][0]['name'] == 'Notes'
        original = owner.resources
        def revoked(*args):
            result = original(*args)
            authz.revoke(f'legacy-compat:{session.plugin_id}:{session.user_id}')
            return result
        owner.resources = revoked
        with pytest.raises(PluginHostError, match='revoked|denied'):
            session.invoke('run')
    finally:
        session.dispose()
