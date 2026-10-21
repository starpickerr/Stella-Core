"""Production owner adapters read through real plugin RPC without copying domains."""
import importlib
from pathlib import Path

import pytest

from core.data.service import DataService, ProviderRegistry
from core.plugins.authz import PluginAuthorizationStore

DOMAINS = ('tasks', 'calendar', 'bills', 'briefing', 'knowledge', 'memory')


@pytest.fixture
def owners(tmp_path, monkeypatch):
    user = tmp_path / 'user'
    monkeypatch.setattr('common.state_dir.user_root', lambda *args, **_: user)
    monkeypatch.setattr('common.state_dir.knowledge_dir', lambda **_: user / 'knowledge')
    monkeypatch.setenv('STELLA_TODOS_PLUGIN_SCHEDULER_SYNC', '0')
    authz = PluginAuthorizationStore()
    modules = {}
    for domain in DOMAINS:
        name = 'todos' if domain == 'tasks' else domain
        gateway = importlib.import_module(f'core.services.{name}_gateway')
        getattr(gateway, f'shutdown_{name}_session')()
        monkeypatch.setattr(gateway, 'DEFAULT_AUTHZ', authz)
        monkeypatch.setenv(f'STELLA_{name.upper()}_PLUGIN', '1')
        monkeypatch.setenv(f'STELLA_{name.upper()}_PLUGIN_ROOT', str(Path('stella-plugins-workspace/plugins') / domain))
        modules[domain] = gateway
    yield user, modules, authz
    for domain, gateway in modules.items():
        getattr(gateway, f'shutdown_{"todos" if domain == "tasks" else domain}_session')()


def seed(domain, user):
    if domain == 'tasks':
        from core.services.todos_facade import TodosPluginFacade
        return TodosPluginFacade().create_todo({'title': 'Owner task'})['id']
    if domain == 'calendar':
        from core.services.calendar_facade import CalendarPluginFacade
        return CalendarPluginFacade().create_event({'title': 'Owner meeting',
            'start_at': '2026-10-21T09:00:00+08:00', 'end_at': '2026-10-21T10:00:00+08:00'})['id']
    if domain == 'bills':
        from core.services.bills_facade import BillsPluginFacade
        return BillsPluginFacade().create_ledger({'name': 'Owner bill', 'category': '消费',
            'entry_type': 'expense', 'amount_minor': 3200, 'occurred_at': '2026-10-21T12:00:00+08:00'})['id']
    if domain == 'briefing':
        from core.services.briefing_facade import BriefingPluginFacade
        return BriefingPluginFacade().start_briefing('2026-10-21').id
    root = user / ('knowledge/notes' if domain == 'knowledge' else 'plugins/memory/memory')
    root.mkdir(parents=True)
    (root / 'owner.md').write_text('# Owner document\nOriginal body', encoding='utf-8')
    return 'notes/owner.md' if domain == 'knowledge' else 'owner.md'


@pytest.mark.parametrize('domain', DOMAINS)
def test_real_owner_resource_search_read_and_revocation(owners, tmp_path, domain):
    from core.data.owned_providers import PluginResourceProvider
    user, modules, authz = owners
    expected = seed(domain, user)
    registry = ProviderRegistry()
    registry.register(domain, PluginResourceProvider(domain))
    service = DataService(tmp_path / 'data.db', registry)
    source = service.discover()['sources'][0]
    page = service.resources(source['id'])
    assert page['total'] == 1
    resource = page['resources'][0]
    assert expected in resource['reference']
    assert resource['provider'] == domain and 'content' not in resource
    content = service.read_resource(source['id'], resource['id'])['content']
    assert content
    assert service.resources(source['id'], 'does-not-exist')['total'] == 0
    with service.store.connection() as db:
        assert db.execute('SELECT count(*) FROM records').fetchone()[0] == 0
    authz.revoke(modules[domain]._GRANT_REF)
    for operation in (lambda: service.resources(source['id']),
                      lambda: service.read_resource(source['id'], resource['id'])):
        with pytest.raises(PermissionError):
            operation()


def test_owner_authorization_probe_does_not_invoke_business_method(owners, monkeypatch):
    from core.services import todos_gateway
    from core.plugins.lifecycle import domain_data_handle
    session = todos_gateway.ensure_todos_session()
    calls = []
    original = session._rpc
    monkeypatch.setattr(session, '_rpc', lambda method, *args, **kwargs: (calls.append(method), original(method, *args, **kwargs))[1])
    result = session.invoke_contract(contract='stella.tasks@1', method='list_todos', input_payload={},
        origin='system', grant_ref=todos_gateway._GRANT_REF, check_only=True,
        data_handle=domain_data_handle('stella.tasks', 'local-default'))
    assert result['status'] == 'succeeded' and 'plugin.invoke' not in calls
    owners[2].revoke(todos_gateway._GRANT_REF)
    with pytest.raises(PermissionError):
        session.invoke_contract(contract='stella.tasks@1', method='list_todos', input_payload={},
            origin='system', grant_ref=todos_gateway._GRANT_REF, check_only=True,
            data_handle=domain_data_handle('stella.tasks', 'local-default'))


def test_owner_revoked_during_read_cannot_return_body(owners, tmp_path, monkeypatch):
    from core.data.owned_providers import PluginResourceProvider
    seed('tasks', owners[0])
    registry = ProviderRegistry()
    registry.register('tasks', PluginResourceProvider('tasks'))
    service = DataService(tmp_path / 'data.db', registry)
    source = service.discover()['sources'][0]
    resource = service.resources(source['id'])['resources'][0]
    gateway = owners[1]['tasks']
    session = gateway.ensure_todos_session()
    original = session._rpc

    def revoke_after_read(method, params, **kwargs):
        result = original(method, params, **kwargs)
        if method == 'plugin.invoke' and params.get('method') == 'get_todo':
            owners[2].revoke(gateway._GRANT_REF)
        return result

    monkeypatch.setattr(session, '_rpc', revoke_after_read)
    with pytest.raises(PermissionError):
        service.read_resource(source['id'], resource['id'])


def test_owner_managed_methods_consumer_purpose_and_disable(owners, tmp_path, monkeypatch):
    from core.data.owned_providers import PluginResourceProvider
    from core.plugins.management import ManagementStore
    from core.plugins.package_ops import PackageStore
    from core.plugins.caller import consumer_plugin_scope
    from common.runtime_identity import identity_scope
    # Seed through the owner before enrolling it; managed reads require explicit grants.
    seed('tasks', owners[0])
    gateway = owners[1]['tasks']
    gateway.shutdown_todos_session()
    store = ManagementStore(tmp_path / 'managed')
    packages = PackageStore(store.root)
    operation = packages.stage(Path('stella-plugins-workspace/plugins/tasks'))
    packages.inspect(operation.operation_id)
    packages.prepare(operation.operation_id)
    packages.commit(operation.operation_id)
    store.set_intent('stella.tasks', 'local-default', 'enabled')
    monkeypatch.setattr('core.plugins.management.default_store', lambda: store)
    registry = ProviderRegistry()
    registry.register('tasks', PluginResourceProvider('tasks'))
    service = DataService(tmp_path / 'data.db', registry)
    source = service.discover()['sources'][0]
    with pytest.raises(PermissionError):
        service.resources(source['id'])
    owners[2].issue_scoped(grant_ref='list', parent_ref=gateway._GRANT_REF,
        plugin_id='stella.tasks', user_id='local-default', consumer_plugin_id='stella.tasks',
        capability='tasks.read', methods=['list_todos'], resources=[{'kind': 'user', 'id': 'local-default'}], purpose='interactive')
    resource = service.resources(source['id'])['resources'][0]
    with pytest.raises(PermissionError):
        service.read_resource(source['id'], resource['id'])
    owners[2].issue_scoped(grant_ref='read', parent_ref=gateway._GRANT_REF,
        plugin_id='stella.tasks', user_id='local-default', consumer_plugin_id='stella.tasks',
        capability='tasks.read', methods=['get_todo'], resources=[{'kind': 'user', 'id': 'local-default'}], purpose='interactive')
    assert service.read_resource(source['id'], resource['id'])['content']['title'] == 'Owner task'
    with consumer_plugin_scope('third.party'), pytest.raises(PermissionError):
        service.read_resource(source['id'], resource['id'])
    with identity_scope(task_id='scheduled-task'), pytest.raises(PermissionError):
        service.resources(source['id'])
    store.set_intent('stella.tasks', 'local-default', 'disabled')
    with pytest.raises(PermissionError):
        service.read_resource(source['id'], resource['id'])
