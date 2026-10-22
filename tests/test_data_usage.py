"""Functional source selections persist separately from grants and event delivery."""
import pytest
from core.data.service import DataService, ProviderRegistry
from tests.test_data_service import Provider


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core.data import usage
    provider = Provider()
    providers = ProviderRegistry()
    providers.register('messages', provider)
    service = DataService(tmp_path / 'data.db', providers)
    service.discover()
    registry = usage.ConsumerRegistry()
    registry.register(usage.DataConsumer('stella.briefing', {'zh': '简报', 'en': 'Briefing'}, frozenset({'messages'}), default_enabled=True))
    registry.register(usage.DataConsumer('example.reader', {'zh': '阅读器', 'en': 'Reader'}, frozenset({'messages'})))
    monkeypatch.setattr(usage, 'DEFAULT_CONSUMERS', registry)
    return service, provider


def test_usage_defaults_persistence_independent_consumers_and_strict_input(env):
    from core.data.usage import UsageService
    service, _ = env
    usage = UsageService(service)
    assert usage.enabled('stella.briefing', 'messages:a')
    assert not usage.enabled('example.reader', 'messages:a')
    usage.set('stella.briefing', 'messages:a', False)
    usage.set('example.reader', 'messages:a', True)
    reopened = UsageService(DataService(service.store.path, service.providers))
    assert not reopened.enabled('stella.briefing', 'messages:a')
    assert reopened.enabled('example.reader', 'messages:a')
    service.discover()
    assert not usage.enabled('stella.briefing', 'messages:a')
    for consumer, source, enabled in [('missing', 'messages:a', True), ('stella.briefing', 'missing', True), ('stella.briefing', 'messages:a', 1)]:
        with pytest.raises((ValueError, KeyError)):
            usage.set(consumer, source, enabled)


@pytest.mark.parametrize('restore', [False, True])
def test_usage_cannot_grant_reads_and_disable_blocks_bound_consumer_results(env, monkeypatch, restore):
    from core.data.usage import UsageService
    from core.plugins.caller import consumer_plugin_scope
    service, provider = env
    usage = UsageService(service)
    service.sync('messages:a')
    usage.set('example.reader', 'messages:a', True)
    provider.allowed = False
    with consumer_plugin_scope('example.reader'), pytest.raises(PermissionError):
        service.resources('messages:a')
    provider.allowed = True
    usage.set('example.reader', 'messages:a', False)
    with consumer_plugin_scope('example.reader'), pytest.raises(PermissionError, match='consumer|usage'):
        service.resources('messages:a')
    # Native resource browsing remains independent of the feature's selection.
    assert service.resources('messages:a')['total'] == 1
    usage.set('example.reader', 'messages:a', True)
    original = service.query
    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        usage.set('example.reader', 'messages:a', False)
        if restore:
            usage.set('example.reader', 'messages:a', True)
        return result
    monkeypatch.setattr(service, 'query', revoke)
    with consumer_plugin_scope('example.reader'), pytest.raises(PermissionError):
        service.resources('messages:a')


def test_usage_revision_blocks_old_collection_without_revoking_other_consumers(env, monkeypatch):
    from core.data.usage import UsageService
    from core.plugins.caller import consumer_plugin_scope
    service, provider = env
    usage = UsageService(service)
    usage.set('example.reader', 'messages:a', True)
    original = provider.fetch
    def change_other_consumer(*args):
        result = original(*args)
        usage.set('stella.briefing', 'messages:a', False)
        return result
    monkeypatch.setattr(provider, 'fetch', change_other_consumer)
    with consumer_plugin_scope('example.reader'):
        assert service.sync('messages:a')['records']
    before = service.store.state('messages:a')['cursors']
    def revoke_and_restore(*args):
        result = original(*args)
        usage.set('example.reader', 'messages:a', False)
        usage.set('example.reader', 'messages:a', True)
        return result
    monkeypatch.setattr(provider, 'fetch', revoke_and_restore)
    with consumer_plugin_scope('example.reader'), pytest.raises(PermissionError):
        service.sync('messages:a')
    assert service.store.state('messages:a')['cursors'] == before


def test_usage_changes_during_final_owner_authorization_are_rejected(env, monkeypatch):
    from core.data.usage import UsageService
    from core.plugins.caller import consumer_plugin_scope
    service, provider = env
    service.sync('messages:a')
    usage = UsageService(service)
    usage.set('example.reader', 'messages:a', True)
    calls = 0
    original = provider.authorize
    def authorize(source, operation):
        nonlocal calls
        original(source, operation)
        if operation == 'read':
            calls += 1
            if calls == 2:
                usage.set('example.reader', 'messages:a', False)
                usage.set('example.reader', 'messages:a', True)
    monkeypatch.setattr(provider, 'authorize', authorize)
    with consumer_plugin_scope('example.reader'), pytest.raises(PermissionError):
        service.query('messages:a')


def test_usage_snapshot_and_native_command_keep_legacy_delivery(env):
    from core.data.api import DataController
    service, _ = env
    controller = DataController(service)
    state = controller.snapshot()
    assert {row['id'] for row in state['usage_consumers']} == {'stella.briefing', 'example.reader'}
    assert state['usages'][0]['source_id'] == 'messages:a'
    result = controller.command({'action': 'usage', 'consumer_id': 'example.reader', 'source_id': 'messages:a', 'enabled': True})
    assert result['usage']['enabled'] is True
    with pytest.raises(ValueError):
        controller.command({'action': 'usage', 'consumer_id': 'example.reader', 'source_id': 'messages:a', 'enabled': True, 'grant': 'forged'})
    assert service.subscriptions() == []


def test_collection_adapter_honors_usage_before_fetch(env, monkeypatch):
    from core.data.usage import UsageService
    from core.data import runtime
    service, _ = env
    monkeypatch.setattr(runtime, 'current_service', lambda: service)
    assert len(runtime.consumer_sources(consumer_id='stella.briefing')) == 1
    UsageService(service).set('stella.briefing', 'messages:a', False)
    assert runtime.consumer_sources(consumer_id='stella.briefing') == []


def test_storage_inventory_includes_actual_domain_and_user_paths(tmp_path, monkeypatch):
    from core.data.storage import inventory, _path_bytes
    from common import state_dir
    monkeypatch.setattr(state_dir, 'user_root', lambda *_, **__: tmp_path / 'user')
    result = inventory()
    rows = {row['id']: row for row in result['categories']}
    assert {'email', 'elearning', 'todos', 'calendar', 'bills', 'knowledge', 'memory', 'plugins', 'work', 'configuration', 'logs'} <= rows.keys()
    assert rows['memory']['path'] == str(tmp_path / 'user/plugins/memory')
    assert not (tmp_path / 'user').exists()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'private')
    folder = tmp_path / 'folder'
    folder.mkdir()
    (folder / 'alias').symlink_to(outside)
    assert _path_bytes(folder) == 0


def test_usage_removal_preparation_failure_and_metadata_only_snapshot(env, monkeypatch):
    from core.data.usage import UsageService
    from core.data.api import DataController
    service, provider = env
    usage = UsageService(service)
    usage.set('stella.briefing', 'messages:a', False, selected=False)
    assert not usage.binding('stella.briefing', 'messages:a')['selected']
    def fail_prepare(source, consumer):
        raise RuntimeError('Owner preparation failed')
    monkeypatch.setattr(provider, 'prepare_usage', fail_prepare, raising=False)
    with pytest.raises(RuntimeError):
        usage.set('stella.briefing', 'messages:a', True)
    service.discover()
    assert not usage.enabled('stella.briefing', 'messages:a')
    # Source discovery and feature selections must not scan every local file.
    monkeypatch.setattr('core.data.storage.inventory', lambda *_: pytest.fail('Storage inventory scanned'))
    assert DataController(service).snapshot(include_storage=False)['storage']['categories'] == []
