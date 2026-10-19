"""Approval is independent from settings selection and binds source/policy revisions."""
from pathlib import Path

import pytest

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.management import ManagementStore
from core.plugins.package_ops import PackageStore


def test_request_survives_restart_and_approval_is_idempotent_but_stale_requests_fail(tmp_path):
    from core.plugins.authorization import AuthorizationService
    management = ManagementStore(tmp_path / 'packages')
    packages = PackageStore(management.root)
    op = packages.stage(Path('stella-plugins-workspace/plugins/bills'))
    packages.inspect(op.operation_id)
    packages.prepare(op.operation_id)
    packages.commit(op.operation_id)
    management.set_intent('stella.bills', 'alice', 'enabled')
    path = tmp_path / 'grants.sqlite'
    authz = PluginAuthorizationStore(path=path)
    service = AuthorizationService(management, authz)
    spec = {'consumerPluginId': 'stella.bills', 'capability': 'bills.read', 'methods': ['list_ledger'],
            'resources': [{'kind': 'user', 'id': 'alice'}], 'purpose': 'interactive', 'reason': '查看账单'}
    request = service.request('stella.bills', 'alice', spec)
    restarted = AuthorizationService(management, PluginAuthorizationStore(path=path))
    grant = restarted.approve('alice', request['requestId'])
    assert restarted.approve('alice', request['requestId']) == grant
    authz.check_scoped(grant_ref='bills-default-grant:alice', plugin_id='stella.bills', user_id='alice',
        consumer_plugin_id='stella.bills', method='list_ledger', required_capabilities=['bills.read'],
        resources=[{'kind': 'user', 'id': 'alice'}], purpose='interactive')
    assert management.settings('stella.bills', 'alice', 'bills.preferences', 'general')['values'] == {}
    stale = service.request('stella.bills', 'alice', spec)
    authz.revoke(grant['grantId'])
    with pytest.raises(PermissionError, match='policy'):
        service.approve('alice', stale['requestId'])
    stale = service.request('stella.bills', 'alice', spec)
    management.bump_source_revision('stella.bills', 'alice')
    with pytest.raises(PermissionError, match='source'):
        service.approve('alice', stale['requestId'])
    pending = service.request('stella.bills', 'alice', spec)
    management.set_intent('stella.bills', 'alice', 'disabled')
    with pytest.raises(PermissionError):
        service.approve('alice', pending['requestId'])


def test_authorization_does_not_accept_other_user_or_undeclared_capability(tmp_path):
    from core.plugins.authorization import AuthorizationService
    management = ManagementStore(tmp_path / 'packages')
    service = AuthorizationService(management, PluginAuthorizationStore())
    with pytest.raises((ValueError, FileNotFoundError, PermissionError)):
        service.request('stella.bills', 'alice', {'consumerPluginId': 'stella.bills', 'capability': 'admin',
            'methods': ['anything'], 'resources': [{'kind': 'user', 'id': 'bob'}], 'purpose': 'interactive'})


def test_consumer_lifecycle_change_invalidates_pending_request(tmp_path):
    from core.plugins.authorization import AuthorizationService
    store = ManagementStore(tmp_path / 'packages')
    packages = PackageStore(store.root)
    for domain in ('bills', 'tasks'):
        op = packages.stage(Path(f'stella-plugins-workspace/plugins/{domain}'))
        packages.inspect(op.operation_id)
        packages.prepare(op.operation_id)
        packages.commit(op.operation_id)
        store.set_intent(f'stella.{domain}', 'alice', 'enabled')
    service = AuthorizationService(store, PluginAuthorizationStore())
    request = service.request('stella.bills', 'alice', {'consumerPluginId': 'stella.tasks', 'capability': 'bills.read',
        'methods': ['list_ledger'], 'resources': [{'kind': 'user', 'id': 'alice'}], 'purpose': 'interactive'})
    store.set_intent('stella.tasks', 'alice', 'disabled')
    store.set_intent('stella.tasks', 'alice', 'enabled')
    with pytest.raises(PermissionError, match='consumer'):
        service.approve('alice', request['requestId'])


def test_approval_rechecks_grant_validity_inside_transaction(monkeypatch):
    from datetime import datetime, timedelta, timezone
    store = PluginAuthorizationStore()
    now = datetime.now(timezone.utc)
    store.create_request({'requestId': 'r', 'userId': 'alice', 'status': 'pending',
        'expiresAt': (now + timedelta(minutes=5)).isoformat(), 'validUntil': (now - timedelta(seconds=1)).isoformat()})
    with pytest.raises(PermissionError, match='validity expired'):
        store.approve_request('r', 'alice', source_revision=1, package_digest='digest')
