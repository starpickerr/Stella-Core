"""Native Data scope selects real workspaces and cannot replace bound authority."""
import pytest

from common.runtime_identity import current_identity, identity_scope
from core.data.resources import Resource
from core.data.service import DataService, ProviderRegistry
from tests.test_data_resources import ReferenceProvider


def test_resource_type_filter_precedes_pagination_and_rechecks_owner(tmp_path):
    class Owner(ReferenceProvider):
        def resources(self, source, query, limit, offset):
            rows = [Resource.from_source(source, str(index), name=str(index),
                    kind='assignment' if index % 2 else 'announcement') for index in range(245)]
            return {'resources': rows[offset:offset + limit], 'total': len(rows)}
    registry = ProviderRegistry()
    registry.register('documents', Owner())
    service = DataService(tmp_path / 'data.db', registry)
    service.discover()
    page = service.resources('documents:library', kind='assignment', offset=100, limit=50)
    assert page['total'] == 122 and len(page['resources']) == 22
    assert all(row['kind'] == 'assignment' for row in page['resources'])
    assert page['resources'][0]['reference'] == '201'
    with pytest.raises(ValueError):
        service.resources('documents:library', kind=['assignment'])


def test_native_scope_resolves_agent_and_workspace_without_privilege_injection(tmp_path, monkeypatch):
    from agent.registry import AgentRegistry
    from agent.workspace import project_store
    from core.data.native import browse_scope
    from core.execution.context import execution_scope, current_execution_context
    registry = AgentRegistry.from_config({'default_agent_id': 'alpha', 'agents': [
        {'id': name, 'name': name, 'workspace': str(tmp_path / name)} for name in ('alpha', 'beta')]})
    monkeypatch.setattr('agent.registry.get_agent_registry', lambda: registry)
    monkeypatch.setattr('agent.workspace.context.personal_work_dir', lambda **_: tmp_path / 'work')
    monkeypatch.setattr(project_store, '_store_file', lambda: str(tmp_path / 'projects.json'))
    with browse_scope('beta', 'chat'):
        context = current_execution_context()
        assert context.origin == 'ui' and current_identity().agent_id == 'beta'
        assert context.workspace.root == tmp_path / 'work/sessions/beta/chat'
    assert current_execution_context() is None and current_identity().agent_id is None
    with pytest.raises((KeyError, ValueError)):
        with browse_scope('unknown', 'chat'):
            pass
    with identity_scope(agent_id='alpha', session_id='private'), execution_scope(origin='tool'):
        with pytest.raises(PermissionError):
            with browse_scope('beta', 'chat'):
                pass
        with browse_scope('alpha', 'private'):
            assert current_execution_context().origin == 'tool'


def test_native_http_browses_selected_workspace_and_denies_another_scope(tmp_path, monkeypatch):
    from agent.registry import AgentRegistry
    from agent.workspace import project_store
    from channel.desktop import desktop_channel as desktop
    from core.data.api import DataController
    from core.data.workspace_provider import WorkspaceProvider
    from tests.test_data_api import call
    registry = AgentRegistry.from_config({'default_agent_id': 'alpha', 'agents': [
        {'id': name, 'name': name, 'workspace': str(tmp_path / name)} for name in ('alpha', 'beta')]})
    monkeypatch.setattr('agent.registry.get_agent_registry', lambda: registry)
    monkeypatch.setattr('agent.workspace.context.personal_work_dir', lambda **_: tmp_path / 'work')
    monkeypatch.setattr(project_store, '_store_file', lambda: str(tmp_path / 'projects.json'))
    monkeypatch.setattr(desktop, '_require_auth', lambda: None)
    monkeypatch.setattr(desktop.web, 'header', lambda *_: None)
    providers = ProviderRegistry()
    providers.register('workspace', WorkspaceProvider())
    service = DataService(tmp_path / 'data.db', providers)
    monkeypatch.setattr('core.data.api.current_controller', lambda: DataController(service))
    root = tmp_path / 'work/sessions/alpha/chat'
    root.mkdir(parents=True)
    (root / 'notes.txt').write_text('Scoped notes')
    snapshot = call(desktop.DataManagementHandler, 'GET', params={'agent': 'alpha', 'session': 'chat', 'refresh': '1'})
    assert snapshot['status'] == 'success'
    source_id = snapshot['sources'][0]['id']
    params = {'agent': 'alpha', 'session': 'chat', 'source_id': source_id}
    page = call(desktop.DataResourcesHandler, 'GET', params=params)
    assert page['resources'][0]['name'] == 'notes.txt'
    params['resource_id'] = page['resources'][0]['id']
    assert call(desktop.DataResourcesHandler, 'GET', params=params)['content'] == 'Scoped notes'
    denied = call(desktop.DataResourcesHandler, 'GET', params={**params, 'agent': 'beta'})
    assert denied['status'] == 'error' and 'content' not in denied
    assert current_identity().agent_id is None
