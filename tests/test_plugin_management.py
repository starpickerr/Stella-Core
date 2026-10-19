"""Persistent management is usable without running plugin code."""

from pathlib import Path

import pytest

from core.plugins.management import ManagementStore, RevisionConflict


def test_intent_and_failure_are_independent_and_user_scoped(tmp_path):
    first = ManagementStore(tmp_path)
    first.set_intent('stella.bills', 'alice', 'disabled')
    first.set_runtime('stella.bills', 'alice', 'failed', error='offline')
    restarted = ManagementStore(tmp_path)
    assert restarted.instance('stella.bills', 'alice')['intent'] == 'disabled'
    assert restarted.instance('stella.bills', 'alice')['state'] == 'stopped'
    assert restarted.instance('stella.bills', 'bob')['intent'] == 'enabled'
    restarted.set_intent('stella.bills', 'alice', 'removed')
    assert ManagementStore(tmp_path).instance('stella.bills', 'alice')['intent'] == 'removed'


def test_settings_compare_and_swap_preserves_other_categories_and_users(tmp_path):
    a = ManagementStore(tmp_path)
    a.save_settings('stella.sample', 'alice', 'preferences', 'general', {'notes': 'saved'}, expected_revision=1)
    b = ManagementStore(tmp_path)
    assert b.settings('stella.sample', 'alice', 'preferences', 'general')['values'] == {'notes': 'saved'}
    with pytest.raises(RevisionConflict):
        b.save_settings('stella.sample', 'alice', 'preferences', 'general', {'notes': 'stale'}, expected_revision=1)
    b.save_settings('stella.sample', 'alice', 'preferences', 'sources', {'selected': []}, expected_revision=1)
    assert a.settings('stella.sample', 'alice', 'preferences', 'general')['revision'] == 2
    assert a.settings('stella.sample', 'bob', 'preferences', 'general')['values'] == {}


def test_management_operation_reopens_with_exact_durable_facts(tmp_path):
    store = ManagementStore(tmp_path)
    operation = store.begin_operation('stella.bills', 'alice', 'upgrade', {'digest': 'fixed'})
    store.advance(operation['operationId'], 'backed_up', {'backupRef': 'backup.sqlite'})
    recovered = ManagementStore(tmp_path).operation(operation['operationId'])
    assert recovered['stage'] == 'backed_up'
    assert recovered['facts'] == {'digest': 'fixed', 'backupRef': 'backup.sqlite'}
    with pytest.raises(ValueError):
        store.set_intent('stella.bills', 'alice', 'active')


def test_disabled_managed_plugin_never_falls_back_or_starts_worker(tmp_path, monkeypatch):
    from core.services import bills_gateway
    from application import Application
    from core.plugins import management

    store = ManagementStore(tmp_path)
    store.set_intent('stella.bills', 'local-default', 'disabled')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    monkeypatch.setenv('STELLA_BILLS_PLUGIN', '0')
    bills_gateway.shutdown_bills_session()
    assert bills_gateway.bills_plugin_enabled()
    port = Application.port('bills')
    with pytest.raises(PermissionError, match='disabled'):
        port.list_ledger(2026, 10)
    assert bills_gateway._SESSION is None


def test_maintenance_closes_new_admission_without_changing_intent(tmp_path, monkeypatch):
    from core.plugins import management
    from core.services import calendar_gateway

    store = ManagementStore(tmp_path)
    store.set_intent('stella.calendar', 'local-default', 'enabled')
    store.set_runtime('stella.calendar', 'local-default', 'maintenance')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    with pytest.raises(PermissionError, match='maintenance'):
        calendar_gateway.ensure_calendar_session()
    assert store.instance('stella.calendar', 'local-default')['intent'] == 'enabled'


def test_disabled_automation_keeps_core_delivery_but_maintenance_blocks_database(tmp_path, monkeypatch):
    from core.plugins import management
    from core.plugins.caller import managed_data_lease

    store = ManagementStore(tmp_path)
    monkeypatch.setattr(management, 'default_store', lambda: store)
    store.set_intent('stella.automation', 'local-default', 'disabled')
    with managed_data_lease('stella.automation', mechanism=True):
        pass
    store.set_runtime('stella.automation', 'local-default', 'maintenance')
    with pytest.raises(PermissionError, match='maintenance'):
        with managed_data_lease('stella.automation', mechanism=True):
            pytest.fail('Core DB writer admitted during maintenance')


def test_settings_schema_validation_and_revisions_are_enforced_without_worker(tmp_path):
    import json
    from core.plugins.settings import PluginSettingsService
    from core.plugins.package_ops import PackageStore
    import shutil

    package = tmp_path / 'sample'
    shutil.copytree('samples/plugins/alpha', package)
    manifest = json.loads((package / 'plugin.json').read_text())
    manifest['contributes']['settings'] = ['preferences']
    (package / 'plugin.json').write_text(json.dumps(manifest))
    (package / 'settings').mkdir()
    descriptor = {'id': 'preferences', 'pluginId': manifest['id'], 'scope': 'user',
                  'categories': [{'id': 'general', 'title': 'General'}], 'fields': [
                      {'key': 'notes', 'title': 'Notes', 'type': 'string', 'category': 'general', 'default': '',
                       'validation': {'maxLength': 20}},
                      {'key': 'password', 'title': 'Password', 'type': 'string', 'category': 'general', 'secret': True}]}
    (package / 'settings/preferences.json').write_text(json.dumps(descriptor))
    store = ManagementStore(tmp_path / 'packages')
    packages = PackageStore(store.root)
    op = packages.stage(package)
    packages.inspect(op.operation_id)
    packages.prepare(op.operation_id)
    packages.commit(op.operation_id)
    service = PluginSettingsService(store)
    saved = service.save(manifest['id'], 'alice', 'preferences', 'general', {'notes': 'retained'}, expected_revision=1)
    assert saved['revision'] == 2
    assert service.read(manifest['id'], 'alice', 'preferences', 'general')['values']['notes'] == 'retained'
    with pytest.raises(RevisionConflict):
        service.save(manifest['id'], 'alice', 'preferences', 'general', {'notes': 'stale'}, expected_revision=1)
    with pytest.raises(ValueError):
        service.save(manifest['id'], 'alice', 'preferences', 'general', {'unexpected': True}, expected_revision=2)
    with pytest.raises(ValueError, match='secret'):
        service.save(manifest['id'], 'alice', 'preferences', 'general', {'password': 'never-store-here'}, expected_revision=2)


def test_managed_install_does_not_issue_full_grant_when_worker_starts(tmp_path, monkeypatch):
    from core.plugins import management
    from core.plugins.authz import PluginAuthorizationStore
    from core.services import bills_gateway
    from core.plugins.registry import PluginRegistry

    store = ManagementStore(tmp_path)
    from core.plugins.package_ops import PackageStore
    packages = PackageStore(store.root)
    op = packages.stage(Path('stella-plugins-workspace/plugins/bills'))
    packages.inspect(op.operation_id)
    packages.prepare(op.operation_id)
    packages.commit(op.operation_id)
    store.set_intent('stella.bills', 'local-default', 'enabled')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    authz = PluginAuthorizationStore()
    monkeypatch.setattr(bills_gateway, 'DEFAULT_AUTHZ', authz)
    monkeypatch.setattr(bills_gateway, 'DEFAULT_REGISTRY', PluginRegistry())
    bills_gateway.shutdown_bills_session()
    try:
        session = bills_gateway.ensure_bills_session()
        assert session.is_running
        assert authz.get(bills_gateway._GRANT_REF) is None
        with pytest.raises(PermissionError, match='unknown grantRef'):
            bills_gateway.invoke_bills('list_ledger', {'year': 2026, 'month': 10}, db_path=tmp_path / 'never.sqlite')
        assert not (tmp_path / 'never.sqlite').exists()
    finally:
        bills_gateway.shutdown_bills_session()
