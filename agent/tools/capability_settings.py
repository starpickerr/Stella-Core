"""Durable enablement intent; enabling never grants execution permission."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3

from common.runtime_identity import current_identity


class CapabilitySettings:
    def __init__(self, workspace_root=None, *, user_id=None):
        from common.state_dir import real_state_root
        self.workspace_root = str(Path(workspace_root or real_state_root()).resolve())
        self.user_id = user_id or current_identity().user_id or 'local-default'
        self.path = Path(self.workspace_root) / 'capabilities.sqlite'

    @staticmethod
    def _validate(kind, name):
        if kind not in {'tool', 'mcp'} or not isinstance(name, str) or not name.strip() or len(name) > 256:
            raise ValueError('invalid capability identifier')
        if any(ord(char) < 32 for char in name):
            raise ValueError('invalid capability identifier')
        if kind == 'tool' and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name):
            raise ValueError('invalid tool identifier')

    def enabled(self, kind, name, default=True):
        self._validate(kind, name)
        if not self.path.exists():
            return default
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
            row = db.execute('SELECT enabled FROM capabilities WHERE user=? AND kind=? AND name=?',
                             (self.user_id, kind, name)).fetchone()
        return bool(row[0]) if row else default

    def set_enabled(self, kind, name, enabled):
        self._validate(kind, name)
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS capabilities(user TEXT,kind TEXT,name TEXT,enabled INTEGER,revision INTEGER,PRIMARY KEY(user,kind,name))')
                db.execute('INSERT INTO capabilities VALUES (?,?,?,?,1) ON CONFLICT(user,kind,name) DO UPDATE SET enabled=excluded.enabled,revision=capabilities.revision+1',
                           (self.user_id, kind, name, int(enabled)))
        return enabled

    def revision(self, kind):
        if not self.path.exists():
            return 0
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
            return db.execute('SELECT COALESCE(SUM(revision),0) FROM capabilities WHERE user=? AND kind=?',
                              (self.user_id, kind)).fetchone()[0]


def tool_enabled(name, *, tool=None, agent_id=None, workspace_root=None):
    store = getattr(tool, '_capability_settings', None)
    if store is not None:
        user = current_identity().user_id
        if user and user != store.user_id:
            raise PermissionError('capability belongs to another user')
    else:
        from common.state_dir import real_state_root
        identity = current_identity()
        if agent_id:
            identity = identity.derive(agent_id=agent_id)
        store = CapabilitySettings(workspace_root or real_state_root(identity), user_id=identity.user_id)
    server = getattr(tool, 'server_name', None)
    return store.enabled('mcp', server) if server else store.enabled('tool', name)
