"""Recoverable migration on an isolated copy, followed by domain-data selection.

The original stays intact until apply+verify and the in-domain marker succeed.
Package selection belongs to the caller; admission remains in maintenance until
that selection is durably complete. No restore may overwrite accepted new data.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3

from core.plugins.host import PluginSession
from core.plugins.locks import package_lock
from core.plugins.management import ManagementStore
from core.plugins.manifest import load_manifest
from core.plugins.package_ops import _sha256_tree
from core.plugins.registry import PluginRegistry


def _db_digest(path: Path) -> str:
    if not path.is_file():
        return 'absent'
    digest = hashlib.sha256()
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
        for line in db.iterdump():
            digest.update(line.encode())
            digest.update(b'\n')
    return digest.hexdigest()


def _marker(path: Path, migration_id: str, schema: int) -> bool:
    if not path.is_file():
        return False
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='_stella_migrations'").fetchone():
            return False
        row = db.execute('SELECT schema_version FROM _stella_migrations WHERE id=?', (migration_id,)).fetchone()
        return row is not None and row[0] == schema


def _checkpoint_database(path: Path):
    with closing(sqlite3.connect(path, timeout=5)) as db:
        if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
            raise RuntimeError('domain database still has an active writer/reader')
        db.execute('PRAGMA journal_mode=DELETE')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('domain database integrity check failed')
    with path.open('rb') as stream:
        os.fsync(stream.fileno())


def _directory_digest(path: Path) -> str:
    return _sha256_tree(path) if path.is_dir() else 'absent'


class MigrationCoordinator:
    def __init__(self, management: ManagementStore):
        self.management = management

    def run(self, package: Path, *, user_id: str, data_handle: dict, operation_id: str | None = None,
            checkpoint=None, drain=None) -> dict:
        package = Path(package).resolve()
        manifest = load_manifest(package)
        plugin_id = manifest['id']
        if data_handle.get('namespace') != plugin_id:
            raise PermissionError('migration namespace mismatch')
        raw_path = data_handle.get('dbPath') or data_handle.get('dataDir')
        if not raw_path:
            raise ValueError('bound domain data required')
        data = Path(raw_path).resolve()
        directory = 'dbPath' not in data_handle
        target = manifest['data']['schemaVersion']
        package_digest = _sha256_tree(package)
        if operation_id:
            operation = self.management.operation(operation_id)
            facts = operation['facts']
            if (operation['pluginId'] != plugin_id or operation['userId'] != user_id or
                    facts['digest'] != package_digest or facts['dataPath'] != str(data)):
                raise PermissionError('migration recovery identity or fixed package mismatch')
            if operation['stage'] == 'repair_required':
                raise RuntimeError('migration repair_required; explicit repair is needed')
        else:
            operation = self.management.begin_operation(plugin_id, user_id, 'migration', {
                'digest': package_digest, 'dataPath': str(data), 'schema': target,
                'packagePath': str(package), 'dataHandle': data_handle,
            })
        op_id = operation['operationId']
        migration_id = f'{plugin_id}:{package_digest}:{hashlib.sha256(user_id.encode()).hexdigest()[:16]}'
        self.management.set_runtime(plugin_id, user_id, 'maintenance')
        if drain:
            drain(plugin_id)
        with package_lock(self.management.root, plugin_id, exclusive=True):
            def advance(stage, facts=None):
                nonlocal operation
                operation = self.management.advance(op_id, stage, facts)
                if checkpoint:
                    checkpoint(stage, operation)

            try:
                facts = operation['facts']
                marker = data / '.stella-migrations.sqlite' if directory else data
                # Selection may have committed immediately before the crash.
                if _marker(marker, migration_id, target):
                    advance('data_selected')
                    return operation
                if operation['stage'] == 'staged':
                    advance('drained')
                facts = operation['facts']
                backup = Path(facts.get('backupRef') or self.management.root / 'management' / 'backups' / op_id / data.name)
                scratch = data.parent / f'.stella-migrate-{op_id}'
                retired = data.parent / f'.stella-retired-{op_id}'
                data.parent.mkdir(parents=True, exist_ok=True)
                if 'backupRef' not in facts:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    if directory:
                        source_digest = _directory_digest(data)
                        if data.exists():
                            shutil.copytree(data, backup, dirs_exist_ok=True)
                        else:
                            backup.mkdir()
                    else:
                        source_digest = _db_digest(data)
                        with closing(sqlite3.connect(backup)) as destination:
                            if data.exists():
                                with closing(sqlite3.connect(f'{data.as_uri()}?mode=ro', uri=True)) as source:
                                    source.backup(destination)
                            destination.commit()
                        _checkpoint_database(backup)
                    advance('backed_up', {'backupRef': str(backup), 'scratchRef': str(scratch),
                                          'retiredRef': str(retired), 'sourceDigest': source_digest,
                                          'migrationId': migration_id})
                facts = operation['facts']
                # No source byte is modified while the working copy is incomplete.
                if operation['stage'] not in {'migrated', 'selecting_data'}:
                    if scratch.exists():
                        shutil.rmtree(scratch) if scratch.is_dir() else scratch.unlink()
                    if directory:
                        shutil.copytree(backup, scratch)
                    else:
                        shutil.copy2(backup, scratch)
                    advance('migrating')
                    handle = {**data_handle, ('dataDir' if directory else 'dbPath'): str(scratch)}
                    session = PluginSession(package, source_label='maintenance', registry=PluginRegistry(),
                                            user_id=user_id, maintenance=True)
                    try:
                        session.start()
                        result = session.migrate(operation_id=op_id, migration_id=migration_id,
                                                 from_schema=0, to_schema=target, data_handle=handle, mode='apply')
                        verified = session.migrate(operation_id=op_id, migration_id=migration_id,
                                                   from_schema=0, to_schema=target, data_handle=handle, mode='verify')
                        if not result['committed'] or not verified['verified']:
                            raise RuntimeError('migration verification failed')
                    finally:
                        session.dispose()
                    marker_copy = scratch / '.stella-migrations.sqlite' if directory else scratch
                    _checkpoint_database(marker_copy)
                    if not _marker(marker_copy, migration_id, target):
                        raise RuntimeError('migration marker missing after apply')
                    advance('migrated')
                if data.exists():
                    current_digest = _directory_digest(data) if directory else _db_digest(data)
                    if current_digest != facts['sourceDigest']:
                        raise RuntimeError('domain data changed during maintenance; refusing overwrite')
                elif facts['sourceDigest'] != 'absent' and not retired.exists():
                    raise RuntimeError('original data vanished during maintenance')
                advance('selecting_data')
                if directory:
                    if data.exists():
                        os.replace(data, retired)
                    os.replace(scratch, data)
                else:
                    if data.exists():
                        _checkpoint_database(data)
                    data.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(scratch, data)
                # Persist directory entry selection, not just the SQLite content.
                descriptor = os.open(data.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                advance('data_selected')
                return operation
            except Exception as exc:
                self.management.advance(op_id, 'repair_required', error=str(exc))
                self.management.set_runtime(plugin_id, user_id, 'maintenance', error=str(exc))
                raise
