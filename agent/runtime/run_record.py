"""Small durable run index; not a replayable model transcript."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from common.state_dir import runs_dir

_recovery_lock = threading.Lock()
_recovered_paths = set()


def _now():
    return datetime.now(timezone.utc).isoformat()


class RunRecord:
    def __init__(self, path=None):
        self.path = Path(path) if path else runs_dir(ensure=True) / "runs.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, request_id TEXT, job_run_id TEXT,
                    user_id TEXT, agent_id TEXT, session_id TEXT, source TEXT NOT NULL,
                    status TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    error TEXT, provider_id TEXT, protocol_id TEXT, model_id TEXT
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    kind TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    step_id TEXT, tool_call_id TEXT, operation_id TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS run_events_by_run ON run_events(run_id,id);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(runs)")}
            for column in ("provider_id", "protocol_id", "model_id"):
                if column not in columns:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {column} TEXT")
        with _recovery_lock:
            if str(self.path) not in _recovered_paths:
                with self._connect() as db:
                    db.execute("""UPDATE runs SET status='outcome_unknown', finished_at=?
                                  WHERE status IN ('queued','running')""", (_now(),))
                _recovered_paths.add(str(self.path))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, run_id, request_id=None, job_run_id=None, user_id=None,
               agent_id=None, session_id=None, source="chat"):
        with self._connect() as db:
            db.execute("""INSERT INTO runs
                (run_id,request_id,job_run_id,user_id,agent_id,session_id,source,status)
                VALUES (?,?,?,?,?,?,?,'queued')""",
                (run_id, request_id, job_run_id, user_id, agent_id, session_id, source))
            db.execute("INSERT INTO run_events(run_id,kind,occurred_at) VALUES (?,'queued',?)",
                       (run_id, _now()))

    def transition(self, run_id, status, error=None):
        now = _now()
        with self._connect() as db:
            if status == "running":
                db.execute("UPDATE runs SET status=?,started_at=? WHERE run_id=?",
                           (status, now, run_id))
            else:
                db.execute("UPDATE runs SET status=?,finished_at=?,error=? WHERE run_id=?",
                           (status, now, error, run_id))
            db.execute("INSERT INTO run_events(run_id,kind,occurred_at) VALUES (?,?,?)",
                       (run_id, status, now))

    def event(self, run_id, kind, *, step_id=None, tool_call_id=None, operation_id=None):
        with self._connect() as db:
            db.execute("""INSERT INTO run_events
                (run_id,kind,occurred_at,step_id,tool_call_id,operation_id)
                VALUES (?,?,?,?,?,?)""",
                (run_id, kind, _now(), step_id, tool_call_id, operation_id))

    def set_model_binding(self, run_id, provider_id, protocol_id, model_id):
        with self._connect() as db:
            db.execute("""UPDATE runs SET provider_id=?,protocol_id=?,model_id=?
                WHERE run_id=?""", (provider_id, protocol_id, model_id, run_id))
