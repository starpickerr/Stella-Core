"""Core package coordinator: fixed candidate → migration → selection.

Management operations use the same PackageStore as bootstrap and distribution.
Uninstall preserves domain data and immutable cache; only explicit enable or
reinstall changes a removed intent. Inventory never starts a worker.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from core.plugins.distribution import check_plugin_api_compatibility, fetch_and_install_from_catalog, load_catalog
from core.plugins.host import PluginSession
from core.plugins.locks import package_lock
from core.plugins.management import ManagementStore
from core.plugins.manifest import load_manifest
from core.plugins.migration import MigrationCoordinator
from core.plugins.package_ops import PackageStore, _sha256_tree
from core.plugins.registry import PluginRegistry
from core.plugins.runtime_hub import DEFAULT_REGISTRY

DOMAINS = {'stella.bills': 'bills', 'stella.tasks': 'todos', 'stella.calendar': 'calendar',
           'stella.briefing': 'briefing', 'stella.email': 'email', 'stella.elearning': 'elearning',
           'stella.automation': 'automation', 'stella.agent-hub': 'agent_hub'}

FIRST_PARTY_PLUGIN_IDS = frozenset(DOMAINS) | frozenset({'stella.agent-hub'})


def domain_data_handle(plugin_id: str, user_id: str) -> dict:
    from common.runtime_identity import identity_scope
    from common import state_dir

    with identity_scope(user_id=user_id):
        if plugin_id in {'stella.bills', 'stella.calendar', 'stella.tasks', 'stella.briefing'}:
            helper = {'stella.bills': state_dir.bills_db, 'stella.calendar': state_dir.calendar_db,
                      'stella.tasks': state_dir.todos_db, 'stella.briefing': state_dir.briefing_db}[plugin_id]
            return {'namespace': plugin_id, 'dbPath': str(helper(ensure=False).resolve())}
        if plugin_id == 'stella.email':
            base = state_dir.briefing_db(ensure=False)
            return {'namespace': plugin_id, 'dbPath': str((base.parent.parent / 'email' / 'email.db').resolve()),
                    'legacyMailboxPath': str(base.with_name('mailbox.json').resolve())}
        if plugin_id == 'stella.elearning':
            base = state_dir.briefing_db(ensure=False).parent
            return {'namespace': plugin_id, 'dataDir': str((base.parent / 'elearning').resolve()), 'legacyDir': str(base.resolve())}
        if plugin_id == 'stella.automation':
            path = state_dir.scheduler_file().with_name('automation.db')
            return {'namespace': plugin_id, 'dbPath': str(path.resolve())}
        if plugin_id == 'stella.agent-hub':
            return {'namespace': plugin_id, 'dbPath': str(state_dir.agent_hub_db(ensure=False).resolve())}
    raise ValueError('no Core domain data handle for this plugin')


def stop_session(plugin_id: str):
    domain = DOMAINS.get(plugin_id)
    if not domain:
        return
    gateway = importlib.import_module(f'core.services.{domain}_gateway')
    session = gateway._SESSION
    if session is not None:
        # Admission is already closed. Interrupt long RPC before waiting for
        # the gateway's serialization lock, then discard its stale cache.
        session.dispose()
        getattr(gateway, f'shutdown_{domain}_session')()


class PluginManager:
    def __init__(self, management: ManagementStore, *, catalog_path: Path):
        self.management = management
        self.catalog_path = Path(catalog_path)
        self.packages = PackageStore(management.root)

    def set_intent(self, plugin_id, user_id, intent) -> dict:
        if intent == 'enabled' and not self.management.has_instance(plugin_id, user_id):
            self.adopt_current(plugin_id, user_id=user_id)
        with package_lock(self.management.root, plugin_id + ':management', exclusive=True):
            return self._set_intent_locked(plugin_id, user_id, intent)

    def _set_intent_locked(self, plugin_id, user_id, intent) -> dict:
        if self.packages.current_package(plugin_id) is None:
            raise FileNotFoundError('plugin is not installed')
        if intent == 'enabled' and self.management.runtime_state(plugin_id, user_id) == 'maintenance':
            raise PermissionError('plugin requires migration recovery before enabling')
        if intent != 'enabled':
            self.management.set_runtime(plugin_id, user_id, 'draining')
            stop_session(plugin_id)
            DEFAULT_REGISTRY.revoke(plugin_id)
        with package_lock(self.management.root, plugin_id + ':policy', exclusive=True):
            result = self.management.set_intent(plugin_id, user_id, intent)
            self.management.set_runtime(plugin_id, user_id, 'stopped')
        if intent == 'enabled':
            from core.plugins.first_party_grants import issue_required_grants_for_enabled_plugin

            issue_required_grants_for_enabled_plugin(plugin_id=plugin_id, user_id=user_id)
        return result

    def install(self, plugin_id, *, user_id, data_handle: dict | None = None, checkpoint=None) -> dict:
        result = fetch_and_install_from_catalog(catalog_path=self.catalog_path, plugin_id=plugin_id,
                                               package_store=self.packages, prepare_only=True)
        if result['status'] != 'prepared':
            raise ValueError(f"package preflight failed: {result['status']}")
        operation = self.management.begin_operation(plugin_id, user_id, 'install', {
            'packageOperationId': result['operationId'], 'candidate': result['path'], 'digest': result['digest'],
            'dataHandle': data_handle, 'migrations': {},
        })
        return self._complete_install(operation, checkpoint=checkpoint)

    def adopt_current(self, plugin_id: str, *, user_id: str) -> dict:
        current = self.packages.current_package(plugin_id)
        if not current or _sha256_tree(Path(current['path'])) != current['digest']:
            raise ValueError('installed package is missing or corrupt; repair required')
        manifest = load_manifest(Path(current['path']))
        if manifest['id'] != plugin_id or manifest['version'] != current['version']:
            raise ValueError('installed package identity mismatch')
        operation = self.management.begin_operation(plugin_id, user_id, 'install', {
            'packageOperationId': current.get('operationId'), 'candidate': current['path'],
            'digest': current['digest'], 'dataHandle': None, 'migrations': {},
        })
        return self._complete_install(operation)

    def resume(self, operation_id: str, *, checkpoint=None) -> dict:
        operation = self.management.operation(operation_id)
        if operation['kind'] != 'install':
            raise ValueError('not a package selection operation')
        if operation['stage'] == 'completed':
            return operation
        return self._complete_install(operation, checkpoint=checkpoint)

    def _complete_install(self, operation: dict, *, checkpoint=None) -> dict:
        with package_lock(self.management.root, operation['pluginId'] + ':management', exclusive=True):
            return self._complete_install_locked(operation, checkpoint=checkpoint)

    def _complete_install_locked(self, operation: dict, *, checkpoint=None) -> dict:
        plugin_id, user_id = operation['pluginId'], operation['userId']
        op_id = operation['operationId']
        facts = operation['facts']
        candidate = Path(facts['candidate'])
        if _sha256_tree(candidate) != facts['digest']:
            raise PermissionError('fixed candidate changed; repair required')
        manifest = load_manifest(candidate)
        if manifest['id'] != plugin_id or not check_plugin_api_compatibility(core_api='1.0.0', package_host_api=manifest['hostApi']).ok:
            raise PermissionError('fixed candidate identity/API mismatch')
        users = sorted(set(self.management.users(plugin_id)) | {user_id})
        for user in users:
            if not self.management.has_instance(plugin_id, user):
                self.management.set_intent(plugin_id, user, 'enabled')
            self.management.set_runtime(plugin_id, user, 'maintenance')
        stop_session(plugin_id)

        def advance(stage, extra=None):
            nonlocal operation
            operation = self.management.advance(op_id, stage, extra)
            if checkpoint:
                checkpoint(stage, operation)

        try:
            if operation['stage'] == 'staged':
                # Handshake and descriptor preflight are not an activation.
                if manifest.get('runtime'):
                    session = PluginSession(candidate, source_label='candidate', registry=PluginRegistry(), maintenance=True)
                    try:
                        session.start()
                    finally:
                        session.dispose()
                advance('prepared')
            migrations = dict(operation['facts'].get('migrations') or {})
            if manifest.get('data'):
                for user in users:
                    handle = (facts.get('dataHandle') if user == user_id else None) or domain_data_handle(plugin_id, user)
                    migration_id = migrations.get(user)
                    # Recover a durable migration started before its operation ID
                    # was copied into the enclosing package operation.
                    if migration_id is None:
                        pending = [op for op in self.management.unfinished(plugin_id)
                                   if op['kind'] == 'migration' and op['userId'] == user and op['facts']['digest'] == facts['digest']]
                        migration_id = pending[0]['operationId'] if pending else None
                    migrated = MigrationCoordinator(self.management).run(candidate, user_id=user, data_handle=handle,
                                                                         operation_id=migration_id)
                    migrations[user] = migrated['operationId']
                    self.management.advance(op_id, operation['stage'], {'migrations': migrations})
                advance('migrated', {'migrations': migrations})
            with package_lock(self.management.root, plugin_id, exclusive=True), package_lock(
                    self.management.root, plugin_id + ':policy', exclusive=True):
                current = self.packages.current_package(plugin_id)
                if not current or current['digest'] != facts['digest']:
                    selected = self.packages.commit(facts['packageOperationId'])
                    if selected.stage.value != 'committed':
                        raise RuntimeError(selected.error or 'package selection failed')
                advance('selected')
                for user, migration_id in migrations.items():
                    self.management.advance(migration_id, 'completed')
                for user in users:
                    self.management.bump_source_revision(plugin_id, user)
                    self.management.set_runtime(plugin_id, user, 'stopped')
                advance('completed')
            from core.plugins.first_party_grants import issue_required_grants_for_enabled_plugin

            current = self.packages.current_package(plugin_id)
            package_root = Path(current['path']) if current else candidate
            for user in users:
                if self.management.instance(plugin_id, user)['intent'] != 'enabled':
                    continue
                issue_required_grants_for_enabled_plugin(
                    plugin_id=plugin_id, user_id=user, package_root=package_root,
                )
            return operation
        except Exception as exc:
            self.management.advance(op_id, 'repair_required', error=str(exc))
            # Never reopen old code against data that may already be migrated.
            for user in users:
                self.management.set_runtime(plugin_id, user, 'maintenance', error=str(exc))
            raise

    def inventory(self, user_id: str) -> list[dict]:
        rows = []
        for pointer in sorted(self.packages.packages.glob('*/current.json')):
            plugin_id = pointer.parent.name
            state = self.management.instance(plugin_id, user_id)
            if not self.management.has_instance(plugin_id, user_id):
                state = {**state, 'intent': 'disabled', 'state': 'stopped'}
            try:
                current = self.packages.current_package(plugin_id)
                manifest = load_manifest(Path(current['path']))
                if (manifest['id'] != plugin_id or manifest['version'] != current['version'] or
                        _sha256_tree(Path(current['path'])) != current['digest']):
                    raise ValueError('installed package identity or digest mismatch')
            except Exception as exc:
                rows.append({**state, 'name': plugin_id, 'state': 'failed', 'error': str(exc),
                             'version': None, 'digest': None, 'manifest': {}, 'services': [],
                             'contributes': {}, 'sourceLabel': 'installed', 'generation': 0,
                             'firstParty': plugin_id in FIRST_PARTY_PLUGIN_IDS,
                             'hideUninstall': plugin_id in FIRST_PARTY_PLUGIN_IDS})
                continue
            snapshot = DEFAULT_REGISTRY.get(plugin_id)
            active = snapshot is not None and snapshot.user_id == user_id and state['intent'] == 'enabled' and state['state'] != 'maintenance'
            rows.append({**state, 'name': manifest['name'], 'version': current['version'], 'digest': current['digest'],
                         'sourceLabel': snapshot.source_label if snapshot else 'installed',
                         'generation': snapshot.generation if active else 0,
                         'state': 'active' if active else ('stopped' if state['state'] in {'active', 'starting', 'validating', 'draining'} else state['state']),
                         'services': list(snapshot.services) if active else [], 'manifest': manifest,
                         'contributes': snapshot.contributes if active else {},
                         'firstParty': plugin_id in FIRST_PARTY_PLUGIN_IDS,
                         'hideUninstall': plugin_id in FIRST_PARTY_PLUGIN_IDS})
        return rows

    def update_plan(self, user_id: str) -> dict:
        from core.plugins.distribution import plan_dual_update
        installed = {row['pluginId']: row for row in self.inventory(user_id)}
        catalog = load_catalog(self.catalog_path)
        updates = []
        for candidate in catalog['plugins']:
            current = installed.get(candidate['pluginId'])
            if current and (current['version'] != candidate.get('version') or current['digest'] != candidate.get('sha256')):
                updates.append({'pluginId': candidate['pluginId'], 'fromVersion': current['version'],
                                'toVersion': candidate['version'], 'hostApi': candidate['hostApi']})
        from cli import __version__

        version = __version__
        plan = plan_dual_update(core_from='1.0.0', core_to='1.0.0', plugin_updates=updates)
        plan['core'] = {'from': version, 'to': version, 'changing': False, 'api': '1.0.0'}
        plan['updates'] = updates
        plan['status'] = 'up_to_date' if not updates else plan['status']
        return plan
