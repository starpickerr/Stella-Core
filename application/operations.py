"""Persist command admission so an unknown result is never blindly replayed."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager

from common.state_dir import user_root


class OutcomeUnknown(RuntimeError):
    pass


class OperationStore:
    def __init__(self):
        root = user_root()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "operations.db"
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT, error TEXT
            )""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def payload_hash(domain, command, args):
        payload = json.dumps([domain, command, args], ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def admit(self, operation_id, payload_hash):
        """Return (was_completed, result); a new command returns (False, None)."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload_hash,status,result FROM operations WHERE operation_id=?",
                             (operation_id,)).fetchone()
            if row:
                if row[0] != payload_hash:
                    raise ValueError("idempotency key reused with different command")
                if row[1] == "completed":
                    return True, json.loads(row[2])
                raise OutcomeUnknown("Previous command outcome is unknown; inspect the business record before retrying")
            db.execute("INSERT INTO operations VALUES (?,?,'started',NULL,NULL)",
                       (operation_id, payload_hash))
            return False, None

    def finish(self, operation_id, value):
        with self._connect() as db:
            db.execute("UPDATE operations SET status='completed',result=? WHERE operation_id=?",
                       (json.dumps(value, ensure_ascii=False, default=str), operation_id))

    def unknown(self, operation_id, error):
        with self._connect() as db:
            db.execute("UPDATE operations SET status='outcome_unknown',error=? WHERE operation_id=?",
                       (str(error), operation_id))
