"""SQLite task and occurrence storage for the desktop scheduler."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from common.runtime_identity import current_identity


def _stamp():
    return datetime.now(timezone.utc).isoformat()


class AutomationStore:
    def __init__(self, legacy_path, agent_id):
        self.legacy_path = Path(legacy_path)
        self.store_path = str(self.legacy_path.with_name("automation.db"))
        self.agent_id = agent_id
        self.lock = threading.RLock()
        self.legacy_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY, owner_agent_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL,
                    next_run_at TEXT, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_due
                    ON tasks(owner_agent_id,owner_user_id,enabled,next_run_at);
                CREATE TABLE IF NOT EXISTS job_runs (
                    job_run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL DEFAULT '',
                    scheduled_at TEXT, manual INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL, lease_until TEXT, attempts INTEGER NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT, error TEXT,
                    result_ref TEXT,
                    UNIQUE(task_id,scheduled_at,manual)
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(job_runs)")}
            if "result_ref" not in columns:
                db.execute("ALTER TABLE job_runs ADD COLUMN result_ref TEXT")
            if "owner_user_id" not in columns:
                db.execute("ALTER TABLE job_runs ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''")
        self._migrate_legacy()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.store_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _migrate_legacy(self):
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM metadata WHERE key='migration_version'").fetchone():
                return
            source = b""
            data = {}
            if self.legacy_path.exists():
                source = self.legacy_path.read_bytes()
                data = json.loads(source)
                if not isinstance(data.get("tasks", {}), dict):
                    raise ValueError("Invalid tasks.json: tasks must be an object")
                backup = self.legacy_path.with_suffix(".json.migration.bak")
                if not backup.exists():
                    shutil.copy2(self.legacy_path, backup)
            for task_id, task in data.get("tasks", {}).items():
                self._write_task(db, task_id, task)
            db.execute("INSERT INTO metadata VALUES ('initialized_defaults',?)",
                       (json.dumps(data.get("initialized_defaults", [])),))
            db.execute("INSERT INTO metadata VALUES ('source_sha256',?)",
                       (hashlib.sha256(source).hexdigest(),))
            db.execute("INSERT INTO metadata VALUES ('migration_version','1')")

    def _write_task(self, db, task_id, task):
        data = dict(task)
        data["id"] = task_id
        data["owner_agent_id"] = data.get("owner_agent_id") or self.agent_id
        data["owner_user_id"] = data.get("owner_user_id") or ""
        if data["owner_agent_id"] != self.agent_id:
            raise ValueError("Task belongs to a different Agent")
        db.execute("""INSERT INTO tasks(task_id,owner_agent_id,owner_user_id,enabled,next_run_at,data)
            VALUES (?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET
            owner_user_id=excluded.owner_user_id,enabled=excluded.enabled,
            next_run_at=excluded.next_run_at,data=excluded.data""",
            (task_id, self.agent_id, data["owner_user_id"] or "",
             int(data.get("enabled", True)), data.get("next_run_at"),
             json.dumps(data, ensure_ascii=False)))

    @staticmethod
    def _current_user():
        return current_identity().user_id or ""

    def load_tasks(self, include_all=False):
        with self.lock, self._connect() as db:
            if include_all:
                rows = db.execute("SELECT task_id,data FROM tasks WHERE owner_agent_id=?", (self.agent_id,))
            else:
                rows = db.execute("""SELECT task_id,data FROM tasks
                    WHERE owner_agent_id=? AND owner_user_id=?""",
                    (self.agent_id, self._current_user()))
            return {row["task_id"]: json.loads(row["data"]) for row in rows}

    def save_tasks(self, tasks, initialized_defaults=None):
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM tasks WHERE owner_agent_id=? AND owner_user_id=?",
                       (self.agent_id, self._current_user()))
            for task_id, task in tasks.items():
                if (task.get("owner_user_id") or "") != self._current_user():
                    raise ValueError("Task belongs to a different user")
                self._write_task(db, task_id, task)
            if initialized_defaults is not None:
                db.execute("""INSERT INTO metadata VALUES ('initialized_defaults',?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                    (json.dumps(initialized_defaults),))

    def ensure_default_task(self, task):
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            defaults = json.loads(db.execute(
                "SELECT value FROM metadata WHERE key='initialized_defaults'").fetchone()[0])
            if task["id"] in defaults:
                return False
            exists = db.execute("SELECT 1 FROM tasks WHERE task_id=?", (task["id"],)).fetchone()
            if not exists:
                self._write_task(db, task["id"], task)
            defaults.append(task["id"])
            db.execute("UPDATE metadata SET value=? WHERE key='initialized_defaults'",
                       (json.dumps(defaults),))
            return not bool(exists)

    def add_task(self, task):
        task_id = task.get("id")
        if not task_id:
            raise ValueError("Task must have an 'id' field")
        if task.get("owner_user_id") not in (None, "", self._current_user()):
            raise ValueError("Task belongs to a different user")
        task = dict(task, owner_user_id=self._current_user())
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone():
                raise ValueError(f"Task with id '{task_id}' already exists")
            self._write_task(db, task_id, task)
        return True

    def update_task(self, task_id, updates):
        if "owner_user_id" in updates or "owner_agent_id" in updates:
            raise ValueError("Task ownership cannot be changed")
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT data FROM tasks WHERE task_id=? AND owner_agent_id=?
                AND owner_user_id=?""", (task_id, self.agent_id, self._current_user())).fetchone()
            if not row:
                raise ValueError(f"Task '{task_id}' not found")
            task = json.loads(row[0])
            task.update(updates)
            task["updated_at"] = datetime.now().isoformat()
            self._write_task(db, task_id, task)
        return True

    def delete_task(self, task_id):
        with self.lock, self._connect() as db:
            deleted = db.execute("""DELETE FROM tasks WHERE task_id=? AND owner_agent_id=?
                AND owner_user_id=?""", (task_id, self.agent_id, self._current_user())).rowcount
        if not deleted:
            raise ValueError(f"Task '{task_id}' not found")
        return True

    def get_task(self, task_id):
        with self.lock, self._connect() as db:
            row = db.execute("""SELECT data FROM tasks WHERE task_id=? AND owner_agent_id=?
                AND owner_user_id=?""", (task_id, self.agent_id, self._current_user())).fetchone()
            return json.loads(row[0]) if row else None

    def list_tasks(self, enabled_only=False, include_all=False):
        tasks = list(self.load_tasks(include_all=include_all).values())
        if enabled_only:
            tasks = [task for task in tasks if task.get("enabled", True)]
        return sorted(tasks, key=lambda task: (not task.get("enabled", True),
                                              task.get("next_run_at") or "9999-12-31"))

    def enable_task(self, task_id, enabled=True):
        return self.update_task(task_id, {"enabled": enabled})

    def claim_occurrence(self, task_id, scheduled_at=None, manual=False, lease_seconds=900):
        if not manual and not scheduled_at:
            raise ValueError("scheduled_at is required for planned runs")
        now = _stamp()
        until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("""SELECT 1 FROM tasks WHERE task_id=? AND
                owner_agent_id=? AND owner_user_id=?""",
                (task_id, self.agent_id, self._current_user())).fetchone():
                return None
            if manual:
                run_id = uuid.uuid4().hex
                db.execute("""INSERT INTO job_runs
                    (job_run_id,task_id,owner_user_id,scheduled_at,manual,status,lease_until,attempts,started_at)
                    VALUES (?,?,?,NULL,1,'running',?,1,?)""",
                    (run_id, task_id, self._current_user(), until, now))
                return run_id
            row = db.execute("""SELECT job_run_id,status,lease_until,attempts FROM job_runs
                WHERE task_id=? AND owner_user_id=? AND scheduled_at=? AND manual=0""",
                (task_id, self._current_user(), scheduled_at)).fetchone()
            if row:
                if row["status"] in ("completed", "outcome_unknown"):
                    return None
                if row["status"] == "running":
                    if row["lease_until"] and row["lease_until"] > now:
                        return None
                    # The previous process may have performed the action before
                    # crashing. A lease timeout cannot prove it is safe to rerun.
                    db.execute("""UPDATE job_runs SET status='outcome_unknown',
                        lease_until=NULL,finished_at=?,error=? WHERE job_run_id=?""",
                        (now, "Execution lease expired; inspect the outcome before retrying",
                         row["job_run_id"]))
                    return None
                db.execute("""UPDATE job_runs SET status='running',lease_until=?,
                    attempts=attempts+1,started_at=?,finished_at=NULL WHERE job_run_id=?""",
                    (until, now, row["job_run_id"]))
                return row["job_run_id"]
            run_id = uuid.uuid4().hex
            db.execute("""INSERT INTO job_runs
                (job_run_id,task_id,owner_user_id,scheduled_at,manual,status,lease_until,attempts,started_at)
                VALUES (?,?,?,?,0,'running',?,1,?)""",
                (run_id, task_id, self._current_user(), scheduled_at, until, now))
            return run_id

    def occurrence_status(self, task_id, scheduled_at):
        with self.lock, self._connect() as db:
            row = db.execute("""SELECT status FROM job_runs WHERE task_id=? AND
                owner_user_id=? AND scheduled_at=? AND manual=0""",
                (task_id, self._current_user(), scheduled_at)).fetchone()
            return row[0] if row else None

    def finish_occurrence(self, job_run_id, success, error=None):
        with self.lock, self._connect() as db:
            db.execute("""UPDATE job_runs SET status=?,lease_until=NULL,finished_at=?,error=?
                WHERE job_run_id=? AND owner_user_id=?""",
                ("completed" if success else "failed", _stamp(), error, job_run_id,
                 self._current_user()))

    def get_execution_ref(self, job_run_id):
        with self.lock, self._connect() as db:
            row = db.execute("SELECT result_ref FROM job_runs WHERE job_run_id=? AND owner_user_id=?",
                             (job_run_id, self._current_user())).fetchone()
            return row[0] if row else None

    def record_execution_ref(self, job_run_id, path):
        with self.lock, self._connect() as db:
            db.execute("UPDATE job_runs SET result_ref=? WHERE job_run_id=? AND owner_user_id=?",
                       (str(path), job_run_id, self._current_user()))
