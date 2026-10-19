from datetime import datetime, timedelta, timezone

import pytest

from core.plugins.authz import PluginAuthorizationStore


def _issue(store, **overrides):
    args = dict(grant_ref='scope-1', parent_ref='email-default-grant', plugin_id='stella.email',
                user_id='alice', consumer_plugin_id='stella.briefing', capability='email.fetch',
                methods=['fetch_messages'], resources=[{'kind': 'folder', 'id': 'mailbox:School'}], purpose='interactive')
    args.update(overrides)
    return store.issue_scoped(**args)


def _check(store, **overrides):
    args = dict(grant_ref='email-default-grant', plugin_id='stella.email', user_id='alice',
                consumer_plugin_id='stella.briefing', method='fetch_messages', required_capabilities=['email.fetch'],
                resources=[{'kind': 'folder', 'id': 'mailbox:School'}], purpose='interactive')
    args.update(overrides)
    return store.check_scoped(**args)


def test_scoped_grant_survives_restart_and_rejects_other_purpose_resource_consumer_method(tmp_path):
    path = tmp_path / 'grants.sqlite'
    store = PluginAuthorizationStore(path=path)
    _issue(store)
    restarted = PluginAuthorizationStore(path=path)
    _check(restarted)
    for change in ({'purpose': 'background'}, {'consumer_plugin_id': 'stella.other'},
                   {'method': 'delete_account'}, {'resources': [{'kind': 'folder', 'id': 'mailbox:Private'}]},
                   {'user_id': 'bob'}):
        with pytest.raises(PermissionError):
            _check(restarted, **change)
    restarted.revoke('scope-1')
    with pytest.raises(PermissionError):
        _check(store)


def test_expired_or_legacy_any_grant_cannot_satisfy_scoped_call():
    store = PluginAuthorizationStore()
    store.issue(grant_ref='email-default-grant', plugin_id='stella.email', user_id='alice',
                capabilities=['email.fetch'], purposes=['any'])
    _issue(store, valid_until=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    with pytest.raises(PermissionError):
        _check(store)


def test_independent_scopes_combine_capabilities_without_expanding_each_resource():
    store = PluginAuthorizationStore()
    _issue(store)
    _issue(store, grant_ref='scope-2', capability='email.read', resources=[{'kind': 'folder', 'id': 'mailbox:Private'}])
    with pytest.raises(PermissionError):
        _check(store, required_capabilities=['email.fetch', 'email.read'])
