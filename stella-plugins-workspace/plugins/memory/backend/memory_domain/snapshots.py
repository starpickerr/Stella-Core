"""Memory-owned change snapshots; restore refuses to overwrite later accepted edits."""
from contextlib import closing
import hashlib
import json
import sqlite3
import uuid


def _db(root):
    db = sqlite3.connect(root / '.snapshots.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS changes(id TEXT,path TEXT,before TEXT,after_hash TEXT,PRIMARY KEY(id,path))')
    return db


def begin(root):
    key = uuid.uuid4().hex
    with closing(_db(root)) as db:
        with db:
            db.execute('INSERT INTO snapshots VALUES (?)', (key,))
    return {'snapshotId': key}


def _require(db, key):
    if not isinstance(key, str) or not db.execute('SELECT 1 FROM snapshots WHERE id=?', (key,)).fetchone():
        raise ValueError('memory snapshot not found')


def record(root, key, path, before, after):
    with closing(_db(root)) as db:
        _require(db, key)
        with db:
            db.execute('INSERT INTO changes VALUES (?,?,?,?) ON CONFLICT(id,path) DO UPDATE SET after_hash=excluded.after_hash',
                (key, path, json.dumps(before), hashlib.sha256(after.encode()).hexdigest()))


def status(root, snapshotId):
    with closing(_db(root)) as db:
        _require(db, snapshotId)
        return {'changed': any(json.loads(before) != ((root / path).read_text(encoding='utf-8') if (root / path).is_file() else None)
            for path,before in db.execute('SELECT path,before FROM changes WHERE id=?', (snapshotId,)))}


def restore(root, snapshotId):
    from memory_domain.documents import write, check_active
    with closing(_db(root)) as db:
        _require(db, snapshotId)
        entries = list(db.execute('SELECT path,before,after_hash FROM changes WHERE id=?', (snapshotId,)))
        changes = []
        for path, raw, expected in entries:
            target = (root / path).resolve()
            if not target.is_relative_to(root):
                raise PermissionError('snapshot path escapes memory')
            before = json.loads(raw)
            current = target.read_text(encoding='utf-8') if target.is_file() else None
            if current == before:
                continue
            if hashlib.sha256((current or '').encode()).hexdigest() != expected:
                raise ValueError('memory restore conflict: a later edit must be preserved')
            changes.append((path,before,current))
        try:
            for path,before,current in changes:
                check_active()
                if before is None:
                    (root / path).unlink(missing_ok=True)
                else:
                    write(root, path, before, expected_hash=hashlib.sha256((current or '').encode()).hexdigest())
        except Exception as exc:
            # Some files may already have been restored. Leave the operation
            # receipt pending/unknown instead of caching a false no-effect
            # failure. The snapshot remains intact: a new explicit restore
            # skips files already at `before` and validates all remaining ones.
            raise RuntimeError('memory restore interrupted; inspect snapshot before retrying') from exc
        return {'restored': True}
