"""Core-owned durable intent, settings revisions and lifecycle operation facts.

Reading management state never imports or starts a plugin. SQLite transactions
serialize writers across processes; runtime state is distinct from user intent.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import uuid


class RevisionConflict(ValueError):
    pass


class ManagementStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / 'management' / 'state.sqlite'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS source_revisions (plugin TEXT NOT NULL, user TEXT NOT NULL,
                    revision INTEGER NOT NULL, PRIMARY KEY(plugin,user));
                CREATE TABLE IF NOT EXISTS instances (
                    plugin TEXT NOT NULL, user TEXT NOT NULL,
                    intent TEXT NOT NULL DEFAULT 'enabled', state TEXT NOT NULL DEFAULT 'stopped',
                    error TEXT, PRIMARY KEY(plugin,user));
                CREATE TABLE IF NOT EXISTS settings (
                    plugin TEXT NOT NULL, user TEXT NOT NULL, settings_id TEXT NOT NULL,
                    category TEXT NOT NULL, revision INTEGER NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY(plugin,user,settings_id,category));
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, plugin TEXT NOT NULL, user TEXT NOT NULL, kind TEXT NOT NULL,
                    stage TEXT NOT NULL, facts TEXT NOT NULL, error TEXT);
            ''')

    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def has_instance(self, plugin_id: str, user_id: str) -> bool:
        with self._db() as db:
            return db.execute('SELECT 1 FROM instances WHERE plugin=? AND user=?', (plugin_id, user_id)).fetchone() is not None

    def runtime_state(self, plugin_id: str, user_id: str) -> str:
        with self._db() as db:
            row = db.execute('SELECT state FROM instances WHERE plugin=? AND user=?', (plugin_id, user_id)).fetchone()
        return row[0] if row else 'stopped'

    def users(self, plugin_id: str) -> list[str]:
        with self._db() as db:
            return [row[0] for row in db.execute('SELECT user FROM instances WHERE plugin=? ORDER BY user', (plugin_id,))]

    def instance(self, plugin_id: str, user_id: str) -> dict:
        with self._db() as db:
            row = db.execute('SELECT * FROM instances WHERE plugin=? AND user=?', (plugin_id, user_id)).fetchone()
        if row is None:
            return {'pluginId': plugin_id, 'userId': user_id, 'intent': 'enabled', 'state': 'stopped', 'error': None}
        return {'pluginId': plugin_id, 'userId': user_id, 'intent': row['intent'],
                'state': row['state'] if row['intent'] == 'enabled' else 'stopped', 'error': row['error']}

    def set_intent(self, plugin_id: str, user_id: str, intent: str) -> dict:
        if intent not in {'enabled', 'disabled', 'removed'}:
            raise ValueError('invalid plugin intent')
        previous = self.instance(plugin_id, user_id)['intent']
        with self._db() as db:
            db.execute('''INSERT INTO instances(plugin,user,intent) VALUES (?,?,?)
                ON CONFLICT(plugin,user) DO UPDATE SET intent=excluded.intent,
                state=CASE WHEN excluded.intent='enabled' THEN instances.state ELSE 'stopped' END''',
                       (plugin_id, user_id, intent))
        if previous != intent:
            self.bump_source_revision(plugin_id, user_id)
        return self.instance(plugin_id, user_id)

    def set_runtime(self, plugin_id: str, user_id: str, state: str, *, error: str | None = None):
        if state not in {'stopped', 'validating', 'starting', 'active', 'degraded', 'blocked', 'failed', 'maintenance', 'draining'}:
            raise ValueError('invalid runtime state')
        with self._db() as db:
            db.execute('''INSERT INTO instances(plugin,user,state,error) VALUES (?,?,?,?)
                ON CONFLICT(plugin,user) DO UPDATE SET state=excluded.state,error=excluded.error''',
                       (plugin_id, user_id, state, error))

    def source_revision(self, plugin_id: str, user_id: str) -> int:
        with self._db() as db:
            row = db.execute('SELECT revision FROM source_revisions WHERE plugin=? AND user=?', (plugin_id, user_id)).fetchone()
        return row[0] if row else 1

    def bump_source_revision(self, plugin_id: str, user_id: str):
        with self._db() as db:
            db.execute('INSERT INTO source_revisions VALUES (?,?,2) ON CONFLICT(plugin,user) DO UPDATE SET revision=revision+1',
                       (plugin_id, user_id))

    def settings(self, plugin_id, user_id, settings_id, category) -> dict:
        with self._db() as db:
            row = db.execute('SELECT revision,value FROM settings WHERE plugin=? AND user=? AND settings_id=? AND category=?',
                             (plugin_id, user_id, settings_id, category)).fetchone()
        return {'revision': row['revision'] if row else 1,
                'values': json.loads(row['value']) if row else {}, 'secretFields': []}

    def save_settings(self, plugin_id, user_id, settings_id, category, changes: dict, *, expected_revision: int) -> dict:
        if not isinstance(changes, dict) or not changes:
            raise ValueError('settings changes must be a nonempty object')
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('invalid settings revision')
        key = (plugin_id, user_id, settings_id, category)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,value FROM settings WHERE plugin=? AND user=? AND settings_id=? AND category=?', key).fetchone()
            revision = row['revision'] if row else 1
            if revision != expected_revision:
                raise RevisionConflict('settings changed; reload and merge the retained draft')
            values = {**(json.loads(row['value']) if row else {}), **changes}
            db.execute('''INSERT INTO settings VALUES (?,?,?,?,?,?) ON CONFLICT(plugin,user,settings_id,category)
                DO UPDATE SET revision=excluded.revision,value=excluded.value''',
                       (*key, revision + 1, json.dumps(values, ensure_ascii=False, allow_nan=False)))
        return self.settings(*key)

    def begin_operation(self, plugin_id, user_id, kind, facts: dict) -> dict:
        operation_id = uuid.uuid4().hex
        with self._db() as db:
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,NULL)',
                       (operation_id, plugin_id, user_id, kind, 'staged', json.dumps(facts, allow_nan=False)))
        return self.operation(operation_id)

    def advance(self, operation_id, stage, facts: dict | None = None, *, error: str | None = None) -> dict:
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT facts FROM operations WHERE id=?', (operation_id,)).fetchone()
            if row is None:
                raise KeyError(operation_id)
            merged = {**json.loads(row['facts']), **(facts or {})}
            db.execute('UPDATE operations SET stage=?,facts=?,error=? WHERE id=?',
                       (stage, json.dumps(merged, allow_nan=False), error, operation_id))
        return self.operation(operation_id)

    def operation(self, operation_id) -> dict:
        with self._db() as db:
            row = db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return {'operationId': row['id'], 'pluginId': row['plugin'], 'userId': row['user'],
                'kind': row['kind'], 'stage': row['stage'], 'facts': json.loads(row['facts']), 'error': row['error']}

    def unfinished(self, plugin_id: str | None = None) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT id FROM operations WHERE stage NOT IN ('completed','failed')").fetchall()
        operations = [self.operation(row['id']) for row in rows]
        return [op for op in operations if plugin_id is None or op['pluginId'] == plugin_id]


def default_store() -> ManagementStore:
    from common.state_dir import shared_root

    return ManagementStore(shared_root() / 'plugin-packages')
