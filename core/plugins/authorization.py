"""Core approval service over the existing plugin authorization policy store."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

from core.plugins.authz import PluginAuthorizationStore, _resource_key, _expiry
from core.plugins.caller import user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.locks import package_lock
from core.plugins.management import ManagementStore
from core.plugins.manifest import load_manifest
from core.plugins.package_ops import PackageStore, _sha256_tree
from core.plugins.registry import PluginRegistry


def grant_spec(grant) -> dict:
    return {'grantId': grant.grant_ref, 'userId': grant.user_id, 'consumerPluginId': grant.consumer_plugin_id,
            'capability': next(iter(grant.capabilities)), 'methods': sorted(grant.methods),
            'resources': [json.loads(key) for key in sorted(grant.resources)],
            'purpose': next(iter(grant.purposes), 'interactive'), 'validUntil': grant.valid_until,
            'policyRevision': grant.policy_revision, 'revoked': grant.revoked}


class AuthorizationService:
    def __init__(self, management: ManagementStore, authz: PluginAuthorizationStore):
        self.management, self.authz = management, authz
        self.packages = PackageStore(management.root)

    @contextmanager
    def _policies(self, *plugin_ids):
        with ExitStack() as stack:
            for plugin_id in sorted(set(plugin_ids)):
                stack.enter_context(package_lock(self.management.root, plugin_id + ':policy', exclusive=True))
            yield

    def _package(self, plugin_id: str, user_id: str):
        state = self.management.instance(plugin_id, user_id)
        if (not self.management.has_instance(plugin_id, user_id) or state['intent'] != 'enabled' or
                self.management.runtime_state(plugin_id, user_id) in {'maintenance', 'draining'}):
            raise PermissionError('plugin is unavailable for authorization')
        current = self.packages.current_package(plugin_id)
        if not current:
            raise FileNotFoundError('plugin is not installed')
        if _sha256_tree(Path(current['path'])) != current['digest']:
            raise PermissionError('installed package changed')
        manifest = load_manifest(Path(current['path']))
        if manifest['id'] != plugin_id or manifest['version'] != current['version']:
            raise PermissionError('installed package identity mismatch')
        return current

    def describe(self, plugin_id: str, user_id: str) -> list[dict]:
        current = self._package(plugin_id, user_id)
        # The control worker publishes no contributions and performs no business read.
        session = PluginSession(Path(current['path']), source_label='authorization-descriptors',
                                registry=PluginRegistry(), user_id=user_id, maintenance=True)
        try:
            prepared = session.start()['prepare']
            return prepared['services']
        finally:
            session.dispose()

    def request(self, plugin_id: str, user_id: str, spec: dict) -> dict:
        allowed = {'consumerPluginId', 'capability', 'methods', 'resources', 'purpose', 'reason', 'validUntil'}
        if not isinstance(spec, dict) or set(spec) - allowed:
            raise ValueError('invalid authorization fields')
        consumer = spec['consumerPluginId']
        consumer_initial = self._package(consumer, user_id)
        provider_initial = self._package(plugin_id, user_id)
        consumer_revision = self.management.source_revision(consumer, user_id)
        provider_revision = self.management.source_revision(plugin_id, user_id)
        methods, resources = spec['methods'], spec['resources']
        if not isinstance(methods, list) or not methods or not all(isinstance(method, str) for method in methods):
            raise ValueError('invalid authorization methods')
        if not isinstance(resources, list) or not resources or len(resources) > 1000:
            raise ValueError('invalid authorization resources')
        for resource in resources:
            _resource_key(resource)
            if resource['kind'] == 'user' and resource['id'] != user_id:
                raise PermissionError('cannot authorize another user namespace')
        if spec['purpose'] not in {'interactive', 'background'}:
            raise ValueError('invalid authorization purpose')
        if spec.get('validUntil') is not None and _expiry(spec['validUntil']) <= datetime.now(timezone.utc):
            raise ValueError('grant expiry is in the past')
        descriptors = self.describe(plugin_id, user_id)
        declared = {row['name']: row for service in descriptors for row in service['methods']}
        for method in methods:
            if method not in declared or spec['capability'] not in declared[method].get('permissions', []):
                raise ValueError('authorization method/capability is not declared')
        with self._policies(plugin_id, consumer):
            current = self._package(plugin_id, user_id)
            consumer_current = self._package(consumer, user_id)
            if (current['digest'] != provider_initial['digest'] or
                    self.management.source_revision(plugin_id, user_id) != provider_revision or
                    consumer_current['digest'] != consumer_initial['digest'] or
                    self.management.source_revision(consumer, user_id) != consumer_revision):
                raise PermissionError('source or consumer changed while preparing authorization')
            manifest = load_manifest(Path(current['path']))
            if spec['capability'] not in {row['capability'] for row in manifest['permissions']}:
                raise ValueError('capability is not declared')
            domain = plugin_id.removeprefix('stella.')
            parent = user_grant_ref(f'{domain}-default-grant', user_id)
            return self.authz.create_request({
                **spec, 'requestId': uuid.uuid4().hex, 'pluginId': plugin_id, 'userId': user_id,
                'methods': sorted(set(methods)), 'grantId': uuid.uuid4().hex, 'parentRef': parent,
                'packageDigest': current['digest'], 'status': 'pending',
                'consumerDigest': consumer_current['digest'], 'consumerRevision': consumer_revision,
                'expectedSourceRevision': self.management.source_revision(plugin_id, user_id),
                'expectedPolicyRevision': self.authz.policy_revision(user_id),
                'expiresAt': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            })

    def approve(self, user_id: str, request_id: str) -> dict:
        request = self.authz.authorization_request(request_id, user_id)
        plugin_id = request['pluginId']
        with self._policies(plugin_id, request['consumerPluginId']):
            current = self._package(plugin_id, user_id)
            consumer = self._package(request['consumerPluginId'], user_id)
            if (consumer['digest'] != request['consumerDigest'] or
                    self.management.source_revision(request['consumerPluginId'], user_id) != request['consumerRevision']):
                raise PermissionError('source/consumer changed; request authorization again')
            return grant_spec(self.authz.approve_request(request_id, user_id,
                source_revision=self.management.source_revision(plugin_id, user_id), package_digest=current['digest']))

    def list(self, user_id: str, plugin_id: str) -> list[dict]:
        return [grant_spec(grant) for grant in self.authz.scoped_grants(user_id, plugin_id=plugin_id)]

    def revoke(self, user_id: str, grant_id: str):
        grant = self.authz.get(grant_id)
        if grant is None or grant.user_id != user_id or not grant.parent_ref:
            raise PermissionError('grant does not belong to this user')
        self.authz.revoke(grant_id)
