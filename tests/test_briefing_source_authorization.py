"""Native Briefing collection inherits existing owner reads, never plugin authority."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.sources.base import FetchResult
from core.plugins.authz import PluginAuthorizationStore
from core.plugins.caller import consumer_plugin_scope, current_consumer_plugin, delegation_scope


@pytest.fixture(params=[
    ('email', 'fetch_messages', 'email.fetch'),
    ('elearning', 'fetch_source', 'elearning.read'),
    ('calendar', 'list_events', 'calendar.read'),
])
def collection(request, tmp_path):
    domain, method, capability = request.param
    user = 'local-default'
    parent = domain + '-default-grant'
    authz = PluginAuthorizationStore(path=tmp_path / 'authorization.sqlite')
    for purpose in ('interactive', 'background'):
        authz.issue_scoped(grant_ref=f'{parent}:{purpose}:{capability}', parent_ref=parent,
            plugin_id='stella.' + domain, user_id=user, consumer_plugin_id='stella.' + domain,
            capability=capability, methods=[method], resources=[{'kind': 'user', 'id': user}], purpose=purpose)
    scope = dict(grant_ref=parent, plugin_id='stella.' + domain, user_id=user,
        consumer_plugin_id='stella.briefing', method=method, required_capabilities=[capability],
        resources=[{'kind': 'user', 'id': user}], purpose='interactive')
    pipeline = BriefingPipeline(service=SimpleNamespace(get_cursor=lambda *args: None), generator=object())

    def fetch(cursors):
        assert current_consumer_plugin() == 'stella.briefing'
        authz.check_scoped(**scope)
        return FetchResult([], errors=['upstream result'])

    # The source seam replaces upstream I/O; pipeline and persisted authorization are real.
    source = SimpleNamespace(name='source', account_id='account', fetch=fetch)
    return authz, scope, pipeline, source


def collect(collection):
    _, _, pipeline, source = collection
    return pipeline._fetch_source(source, '2026-10-21T00:00:00Z', '2026-10-22T00:00:00Z')


@pytest.mark.parametrize('purpose', ['interactive', 'background'])
def test_native_collection_with_default_owner_grants_keeps_consumer_and_purpose(collection, purpose):
    authz, scope, _, _ = collection
    scope['purpose'] = purpose
    assert collect(collection).errors == ['upstream result']
    # This is host collection authority, not a new persistent plugin grant.
    assert len(authz.scoped_grants('local-default')) == 2
    with consumer_plugin_scope('stella.briefing'), pytest.raises(PermissionError):
        authz.check_scoped(**scope)


def test_owner_revocation_and_restoration_remain_authoritative(collection):
    authz, scope, _, _ = collection
    assert collect(collection)
    ref = f"{scope['grant_ref']}:interactive:{scope['required_capabilities'][0]}"
    authz.revoke(ref)
    with pytest.raises(PermissionError):
        collect(collection)
    authz.update_owned(ref, user_id='local-default', revision=2, revoked=False)
    assert collect(collection)


def test_explicit_consumer_restrictions_are_never_replaced_by_owner_defaults(collection):
    authz, scope, _, _ = collection
    authz.issue_scoped(grant_ref='explicit', parent_ref=scope['grant_ref'], plugin_id=scope['plugin_id'],
        user_id='local-default', consumer_plugin_id='stella.briefing',
        capability=scope['required_capabilities'][0], methods=[scope['method']],
        resources=scope['resources'], purpose='interactive')
    assert collect(collection)
    authz.revoke('explicit')
    with pytest.raises(PermissionError):
        collect(collection)
    scope['purpose'] = 'background'
    with pytest.raises(PermissionError):
        collect(collection)
    authz.update_owned('explicit', user_id='local-default', revision=2, revoked=False)
    scope['purpose'] = 'interactive'
    assert collect(collection)


@pytest.mark.parametrize('restriction', ['purpose', 'expiry', 'parent'])
def test_inherited_owner_purpose_expiry_and_parent_revocation_are_not_relaxed(collection, restriction):
    authz, scope, _, _ = collection
    assert collect(collection)
    ref = f"{scope['grant_ref']}:interactive:{scope['required_capabilities'][0]}"
    if restriction == 'purpose':
        authz.update_owned(ref, user_id='local-default', revision=1, purposes=frozenset())
    elif restriction == 'expiry':
        authz.update_owned(ref, user_id='local-default', revision=1, valid_until='2000-01-01T00:00:00Z')
    else:
        authz.issue(grant_ref=scope['grant_ref'], plugin_id=scope['plugin_id'], user_id='local-default',
            capabilities=[], purposes=['any'])
        authz.revoke(scope['grant_ref'])
    with pytest.raises(PermissionError):
        collect(collection)


@pytest.mark.parametrize('change', ['method', 'capability', 'user', 'consumer', 'resource', 'callback'])
def test_native_collection_cannot_widen_authority(collection, change):
    authz, scope, _, source = collection
    if change == 'method':
        scope['method'] = 'save_settings'
    elif change == 'capability':
        scope['required_capabilities'] = ['calendar.write']
    elif change == 'user':
        scope['user_id'] = 'other-user'
    elif change == 'consumer':
        scope['consumer_plugin_id'] = 'third.party'
    elif change == 'resource':
        scope['resources'] = [{'kind': 'user', 'id': 'other-user'}]
        # Owner scope does not authorize a different user namespace.
        ref = f"{scope['grant_ref']}:interactive:{scope['required_capabilities'][0]}"
        authz.update_owned(ref, user_id='local-default', revision=1,
            resources=frozenset({'{"id":"account","kind":"account"}'}))
    else:
        def callback(cursors):
            context = {'origin': 'ui', 'delegationChain': []}
            with delegation_scope(context, 'stella.briefing', datetime.now(timezone.utc) + timedelta(seconds=10)):
                authz.check_scoped(**scope)
            return FetchResult([])
        source.fetch = callback
    with pytest.raises(PermissionError):
        collect(collection)
