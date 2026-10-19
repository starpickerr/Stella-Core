"""Production host dispatch must enforce scoped grants, including actual sources."""
from pathlib import Path

import pytest

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.host import PluginSession
from core.plugins.management import ManagementStore
from core.plugins.registry import PluginRegistry


@pytest.fixture
def managed(tmp_path, monkeypatch):
    from core.plugins import management
    store = ManagementStore(tmp_path / 'packages')
    from core.plugins.package_ops import PackageStore
    packages = PackageStore(store.root)
    operation = packages.stage(Path('stella-plugins-workspace/plugins/bills'))
    packages.inspect(operation.operation_id)
    packages.prepare(operation.operation_id)
    packages.commit(operation.operation_id)
    store.set_intent('stella.bills', 'local-default', 'enabled')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    authz = PluginAuthorizationStore()
    session = PluginSession(Path('stella-plugins-workspace/plugins/bills'), source_label='test',
                            registry=PluginRegistry(), authz=authz)
    session.start()
    yield session, authz
    session.dispose()


def test_managed_host_ignores_legacy_full_grants_and_refuses_bypass(managed, tmp_path):
    session, authz = managed
    authz.issue(grant_ref='g', plugin_id='stella.bills', user_id='local-default', capabilities=['bills.read'], purposes=['any'])
    for bypass in (False, True):
        with pytest.raises(PermissionError):
            session.invoke_contract(contract='stella.bills@1', method='list_ledger', input_payload={}, origin='ui',
                                    grant_ref='g', skip_authz=bypass,
                                    data_handle={'dbPath': str(tmp_path / 'never.sqlite'), 'namespace': 'stella.bills'})
    assert not (tmp_path / 'never.sqlite').exists()


def test_managed_host_accepts_approved_scope_and_job_cannot_use_interactive_grant(managed, tmp_path):
    session, authz = managed
    authz.issue_scoped(grant_ref='approved', parent_ref='g', plugin_id='stella.bills', user_id='local-default',
                       consumer_plugin_id='stella.bills', capability='bills.read', methods=['list_ledger'],
                       resources=[{'kind': 'user', 'id': 'local-default'}], purpose='interactive')
    result = session.invoke_contract(contract='stella.bills@1', method='list_ledger', input_payload={'year': 2026, 'month': 10},
                                     origin='ui', grant_ref='g',
                                     data_handle={'dbPath': str(tmp_path / 'bills.sqlite'), 'namespace': 'stella.bills'})
    assert result['status'] == 'succeeded'
    from common.runtime_identity import identity_scope
    with identity_scope(task_id='background-task'):
        with pytest.raises(PermissionError, match='background'):
            session.invoke_contract(contract='stella.bills@1', method='list_ledger', input_payload={}, origin='system', grant_ref='g')


def test_email_scope_is_resolved_from_actual_folder_not_supplied_resource_hint(tmp_path, monkeypatch):
    from core.plugins.resources import invocation_resources
    calls = []

    def metadata(method, params):
        calls.append((method, params))
        return {'source_account_id': 'actual-private-folder'}

    resources = invocation_resources('stella.email', 'fetch_messages',
        {'account_id': 'account', 'folder': 'approved-folder'}, 'alice', metadata)
    assert resources == [{'kind': 'folder', 'id': 'actual-private-folder'}]
    assert calls == [('get_account', {'account_id': 'account'})]
    authz = PluginAuthorizationStore()
    authz.issue_scoped(grant_ref='g1', parent_ref='g', plugin_id='stella.email', user_id='alice',
        consumer_plugin_id='stella.briefing', capability='email.fetch', methods=['fetch_messages'],
        resources=[{'kind': 'folder', 'id': 'approved-folder'}], purpose='interactive')
    with pytest.raises(PermissionError):
        authz.check_scoped(grant_ref='g', plugin_id='stella.email', user_id='alice', consumer_plugin_id='stella.briefing',
            method='fetch_messages', required_capabilities=['email.fetch'], resources=resources, purpose='interactive')


def test_unfiltered_course_read_requires_full_configured_scope_and_empty_config_is_not_empty_authority():
    from core.plugins.resources import invocation_resources

    assert invocation_resources('stella.elearning', 'fetch_source', {}, 'alice',
        lambda *_: {'account_id': 'school', 'courses': ['1', '2']}) == [{'kind': 'course', 'id': 'school:1'}, {'kind': 'course', 'id': 'school:2'}]
    assert invocation_resources('stella.elearning', 'fetch', {}, 'alice',
        lambda *_: {'courses': []}) == [{'kind': 'user', 'id': 'alice'}]


def test_explicit_empty_course_filter_is_an_all_courses_request():
    from core.plugins.resources import invocation_resources
    assert invocation_resources('stella.elearning', 'fetch', {'course_ids': []}, 'alice',
        lambda *_: {'courses': ['C1']}) == [{'kind': 'user', 'id': 'alice'}]


def test_other_process_package_selection_invalidates_existing_worker(managed, tmp_path, monkeypatch):
    import json
    import shutil
    from core.plugins.management import default_store
    from core.plugins.package_ops import PackageStore
    session, authz = managed
    authz.issue_scoped(grant_ref='approved', parent_ref='g', plugin_id='stella.bills', user_id='local-default',
        consumer_plugin_id='stella.bills', capability='bills.read', methods=['list_ledger'],
        resources=[{'kind': 'user', 'id': 'local-default'}], purpose='interactive')
    replacement = tmp_path / 'replacement'
    shutil.copytree(session.plugin_root, replacement)
    manifest = json.loads((replacement / 'plugin.json').read_text())
    manifest['version'] = '2.0.0'
    (replacement / 'plugin.json').write_text(json.dumps(manifest))
    packages = PackageStore(default_store().root)
    op = packages.stage(replacement)
    packages.inspect(op.operation_id)
    packages.prepare(op.operation_id)
    packages.commit(op.operation_id)
    assert not session.is_running
    with pytest.raises(PermissionError, match='selection'):
        session.invoke_contract(contract='stella.bills@1', method='list_ledger', input_payload={},
                                origin='ui', grant_ref='g')
