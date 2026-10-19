"""Maintenance-only migration control. No contributions or business dispatch."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sqlite3


def migrate(params, state) -> dict:
    required = {'operationId', 'migrationId', 'mode', 'fromSchema', 'toSchema', 'dataHandle', 'deadline', '_hostDataHandle'}
    if set(params) != required:
        raise ValueError('invalid migration parameters')
    for key in ('operationId', 'migrationId', 'dataHandle'):
        if not isinstance(params[key], str) or not params[key] or len(params[key]) > 256:
            raise ValueError('invalid migration identity')
    if params['mode'] not in {'apply', 'verify'}:
        raise ValueError('invalid migration mode')
    if type(params['fromSchema']) is not int or params['fromSchema'] < 0:
        raise ValueError('invalid fromSchema')
    target = (state.manifest.get('data') or {}).get('schemaVersion')
    if type(params['toSchema']) is not int or params['toSchema'] != target:
        raise ValueError('migration target schema mismatch')
    if params['fromSchema'] > target:
        raise PermissionError('domain schema downgrade refused')
    deadline = datetime.fromisoformat(params['deadline'].replace('Z', '+00:00'))
    if deadline.tzinfo is None or deadline <= datetime.now(timezone.utc):
        raise PermissionError('migration deadline expired')
    handle = params['_hostDataHandle']
    if (handle.get('namespace') != state.plugin_id or handle.get('userId') != state.user_id or
            handle.get('instanceId') != state.instance_id or handle.get('generation') != state.generation):
        raise PermissionError('migration data handle identity mismatch')
    entry = (state.manifest.get('data') or {}).get('migrationEntry')
    if not isinstance(entry, str):
        raise ValueError('migration entry missing')
    path = (state.root / entry).resolve()
    if not path.is_relative_to(state.root.resolve()) or not path.is_file():
        raise PermissionError('migration entry escapes package or missing')
    spec = importlib.util.spec_from_file_location('stella_plugin_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw_db = handle.get('dbPath')
    raw_dir = handle.get('dataDir')
    if not raw_db and not raw_dir:
        raise ValueError('migration requires a bound domain data handle')
    marker_path = Path(raw_db) if raw_db else Path(raw_dir) / '.stella-migrations.sqlite'
    committed = False
    migration_id = params['migrationId']
    if marker_path.is_file():
        with closing(sqlite3.connect(f'{marker_path.as_uri()}?mode=ro', uri=True)) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='_stella_migrations'").fetchone()
            if exists:
                row = db.execute('SELECT schema_version FROM _stella_migrations WHERE id=?', (migration_id,)).fetchone()
                if row and row[0] != target:
                    raise ValueError('migration identity reused for another schema')
                committed = row is not None
    if params['mode'] == 'apply' and not committed:
        result = module.apply(migration_id, handle)
        if not result.get('applied') or result.get('schemaVersion') != target:
            raise RuntimeError('migration apply did not confirm target schema')
        verified = module.verify(migration_id, handle)
        if not verified.get('verified') or verified.get('schemaVersion') != target:
            raise RuntimeError('migration verification failed')
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(marker_path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS _stella_migrations (id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL)')
            db.execute('INSERT INTO _stella_migrations VALUES (?,?)', (migration_id, target))
        committed = True
    checked = module.verify(migration_id, handle)
    return {'migrationId': migration_id, 'schemaVersion': target, 'committed': committed,
            'verified': bool(checked.get('verified')) and checked.get('schemaVersion') == target}
