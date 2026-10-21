"""User-scoped records, transactional change events and independent deliveries."""

from contextlib import contextmanager, closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


def encode(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def stable_id(*parts):
    return hashlib.sha256(encode(parts).encode()).hexdigest()


def reference(item):
    return {
        **item,
        "payload": {},
        "snippet": "",
        "sender": "",
        "sender_email": "",
        "list_id": "",
        "thread_id": "",
    }


def matches(filter, item, event_type):
    return (
        event_type in filter.get("event_types", ["created", "updated", "deleted"])
        and filter.get("q", "").casefold()
        in (item.get("title", "") + " " + item.get("snippet", "")).casefold()
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY,provider TEXT NOT NULL,spec TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,
 storage TEXT NOT NULL DEFAULT 'persistent',retention_days INTEGER NOT NULL DEFAULT 30,revision INTEGER NOT NULL DEFAULT 1,
 present INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sync_state(
 source_id TEXT PRIMARY KEY REFERENCES sources(id),cursors TEXT NOT NULL DEFAULT '{}',
 lease TEXT,lease_until REAL NOT NULL DEFAULT 0,last_run REAL,error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS records(
 id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),external_id TEXT NOT NULL,
 content TEXT NOT NULL,digest TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,updated_at REAL NOT NULL,
 UNIQUE(source_id,external_id));
CREATE INDEX IF NOT EXISTS records_source ON records(source_id,updated_at);
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,source_id TEXT NOT NULL REFERENCES sources(id),
 record_id TEXT NOT NULL,type TEXT NOT NULL,version TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions(
 id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),consumer TEXT NOT NULL,
 filter TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS deliveries(
 subscription_id TEXT NOT NULL REFERENCES subscriptions(id),event_id TEXT NOT NULL REFERENCES events(id),
 state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,
 lease_until REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',delivered_at REAL,
 PRIMARY KEY(subscription_id,event_id));
"""


class DataStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise PermissionError("Data database may not use a symlink target")
        descriptor = os.open(
            self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        with self.connection() as db:
            db.executescript(SCHEMA)
            if "present" not in {
                row["name"] for row in db.execute("PRAGMA table_info(sources)")
            }:
                db.execute(
                    "ALTER TABLE sources ADD COLUMN present INTEGER NOT NULL DEFAULT 1"
                )

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db

    def source(self, source_id, db=None):
        if db is None:
            with self.connection() as db:
                return self.source(source_id, db)
        row = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise KeyError("Data source not found")
        return {
            **json.loads(row["spec"]),
            "provider": row["provider"],
            "enabled": bool(row["enabled"]),
            "present": bool(row["present"]),
            "storage": row["storage"],
            "retention_days": row["retention_days"],
            "revision": row["revision"],
        }

    def sources(self):
        with self.connection() as db:
            return [
                self.source(row["id"], db)
                for row in db.execute("SELECT id FROM sources ORDER BY id")
            ]

    def discover(self, provider, spec):
        with self.connection() as db:
            previous = db.execute(
                "SELECT provider,spec FROM sources WHERE id=?", (spec["id"],)
            ).fetchone()
            if previous and previous["provider"] != provider:
                raise ValueError("Source identity belongs to another provider")
            db.execute(
                """INSERT INTO sources(id,provider,spec) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET spec=excluded.spec,
                revision=revision+CASE WHEN spec=excluded.spec THEN 0 ELSE 1 END""",
                (spec["id"], provider, encode(spec)),
            )
            db.execute(
                "INSERT OR IGNORE INTO sync_state(source_id) VALUES(?)", (spec["id"],)
            )

    def reconcile_presence(self, provider, identifiers):
        """Only a complete successful discovery may withdraw an existing source."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(
                "SELECT id,present FROM sources WHERE provider=?", (provider,)
            ).fetchall():
                present = row["id"] in identifiers
                if present != bool(row["present"]):
                    db.execute(
                        "UPDATE sources SET present=?,revision=revision+1 WHERE id=?",
                        (present, row["id"]),
                    )

    def configure(self, source_id, values):
        with self.connection() as db:
            self.source(source_id, db)
            db.execute("BEGIN IMMEDIATE")
            for field, value in values.items():
                if field not in {"enabled", "storage", "retention_days"}:
                    raise ValueError("Unsupported source setting")
                db.execute(
                    f"UPDATE sources SET {field}=?,revision=revision+1 WHERE id=?",
                    (value, source_id),
                )
            if values.get("storage") == "reference":
                for row in db.execute(
                    "SELECT * FROM records WHERE source_id=? AND deleted=0",
                    (source_id,),
                ).fetchall():
                    item = reference(json.loads(row["content"]))
                    content = encode(item)
                    digest = hashlib.sha256(content.encode()).hexdigest()
                    if digest != row["digest"]:
                        db.execute(
                            "UPDATE records SET content=?,digest=?,updated_at=? WHERE id=?",
                            (content, digest, time.time(), row["id"]),
                        )
                        self.append_event(
                            db, source_id, row["id"], "updated", digest, item
                        )
        return self.source(source_id)

    def state(self, source_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM sync_state WHERE source_id=?", (source_id,)
            ).fetchone()
            if row is None:
                raise KeyError("Data source not found")
            return {
                "source_id": source_id,
                "cursors": json.loads(row["cursors"]),
                "running": bool(row["lease"] and row["lease_until"] > time.time()),
                "last_run": row["last_run"],
                "error": row["error"],
            }

    def claim_sync(self, source_id):
        token = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            source = self.source(source_id, db)
            if not source["enabled"]:
                raise PermissionError("Data source is disabled")
            row = db.execute(
                "SELECT * FROM sync_state WHERE source_id=?", (source_id,)
            ).fetchone()
            if row["lease"] and row["lease_until"] > time.time():
                raise RuntimeError("Data source is already syncing")
            db.execute(
                "UPDATE sync_state SET lease=?,lease_until=?,error=? WHERE source_id=?",
                (token, time.time() + 900, "", source_id),
            )
            return token, json.loads(row["cursors"]), source["revision"]

    def finish_sync(self, source_id, token, error=""):
        with self.connection() as db:
            db.execute(
                "UPDATE sync_state SET lease=NULL,lease_until=0,error=?,last_run=? WHERE source_id=? AND lease=?",
                (str(error)[:1000], time.time(), source_id, token),
            )

    def append_event(self, db, source_id, record_id, event_type, version, item):
        identifier = uuid.uuid4().hex
        db.execute(
            "INSERT INTO events(id,source_id,record_id,type,version,created_at) VALUES(?,?,?,?,?,?)",
            (identifier, source_id, record_id, event_type, version, time.time()),
        )
        for subscription in db.execute(
            "SELECT * FROM subscriptions WHERE source_id=? AND enabled=1", (source_id,)
        ).fetchall():
            if matches(json.loads(subscription["filter"]), item, event_type):
                db.execute(
                    "INSERT INTO deliveries(subscription_id,event_id) VALUES(?,?)",
                    (subscription["id"], identifier),
                )

    def commit_batch(self, source_id, token, revision, items, cursors, authorize):
        result = []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            source = self.source(source_id, db)
            row = db.execute(
                "SELECT lease FROM sync_state WHERE source_id=?", (source_id,)
            ).fetchone()
            if not source["enabled"]:
                raise PermissionError("Data source is disabled")
            if source["revision"] != revision or row["lease"] != token:
                raise PermissionError("Source configuration or sync generation changed")
            authorize()
            for item in items:
                item = dict(item)
                if source["storage"] == "reference":
                    item = reference(item)
                external_id = encode(
                    [item["source"], item["account_id"], item["source_id"]]
                )
                identifier = stable_id(source_id, external_id)
                content = encode(item)
                digest = hashlib.sha256(content.encode()).hexdigest()
                prior = db.execute(
                    "SELECT digest,deleted FROM records WHERE id=?", (identifier,)
                ).fetchone()
                changed = prior is None or prior["deleted"] or prior["digest"] != digest
                if changed:
                    db.execute(
                        """INSERT INTO records(id,source_id,external_id,content,digest,updated_at) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET content=excluded.content,digest=excluded.digest,deleted=0,updated_at=excluded.updated_at""",
                        (
                            identifier,
                            source_id,
                            external_id,
                            content,
                            digest,
                            time.time(),
                        ),
                    )
                    self.append_event(
                        db,
                        source_id,
                        identifier,
                        "created" if prior is None else "updated",
                        digest,
                        item,
                    )
                elif source["storage"] == "cache":
                    db.execute(
                        "UPDATE records SET updated_at=? WHERE id=?",
                        (time.time(), identifier),
                    )
                result.append(
                    {
                        "id": identifier,
                        "source_id": source_id,
                        "item": item,
                        "version": digest,
                    }
                )
            db.execute(
                "UPDATE sync_state SET cursors=? WHERE source_id=? AND lease=?",
                (encode(cursors), source_id, token),
            )
        return result

    def record(self, record_id):
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM records WHERE id=?", (record_id,)
            ).fetchone()
            if row is None:
                raise KeyError("Data record not found")
            return dict(row)

    def tombstone(self, db, row):
        if row["deleted"]:
            return False
        item = json.loads(row["content"])
        # Keep only a reference after a user deletion/cache cleanup, including
        # event delivery. Business snapshots and the upstream stay untouched.
        reference = {
            **item,
            "payload": {},
            "snippet": "",
            "title": "",
            "sender": "",
            "sender_email": "",
            "list_id": "",
        }
        db.execute(
            "UPDATE records SET deleted=1,content=?,updated_at=? WHERE id=?",
            (encode(reference), time.time(), row["id"]),
        )
        self.append_event(
            db, row["source_id"], row["id"], "deleted", row["digest"], item
        )
        return True
