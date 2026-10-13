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
                CREATE TABLE IF NOT EXISTS job_deliveries (
                    job_run_id TEXT NOT NULL, leg TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL DEFAULT '',
                    channel_type TEXT NOT NULL, receiver TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    platform_response TEXT, error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_run_id,leg)
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(job_runs)")}
            if "result_ref" not in columns:
                db.execute("ALTER TABLE job_runs ADD COLUMN result_ref TEXT")
            if "owner_user_id" not in columns:
                db.execute("ALTER TABLE job_runs ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT ''")
            if "retryable" not in columns:
                db.execute("ALTER TABLE job_runs ADD COLUMN retryable INTEGER NOT NULL DEFAULT 1")
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

    def save_tasks(self, tasks):
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM tasks WHERE owner_agent_id=? AND owner_user_id=?",
                       (self.agent_id, self._current_user()))
            for task_id, task in tasks.items():
                if (task.get("owner_user_id") or "") != self._current_user():
                    raise ValueError("Task belongs to a different user")
                self._write_task(db, task_id, task)
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
            for key, value in updates.items():
                if key == "run_permission_mode" and value is None:
                    task.pop(key, None)
                else:
                    task[key] = value
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
            row = db.execute("""SELECT job_run_id,status,lease_until,attempts,retryable,result_ref FROM job_runs
                WHERE task_id=? AND owner_user_id=? AND scheduled_at=? AND manual=0""",
                (task_id, self._current_user(), scheduled_at)).fetchone()
            if row:
                if row["status"] in ("completed", "outcome_unknown") or (row["status"] == "failed" and not row["retryable"]):
                    return None
                if row["status"] == "running":
                    if row["lease_until"] and row["lease_until"] > now:
                        return None
                    delivery_states = {item[0] for item in db.execute(
                        "SELECT status FROM job_deliveries WHERE job_run_id=?", (row["job_run_id"],))}
                    if "accepted" in delivery_states:
                        db.execute("""UPDATE job_runs SET status='completed',lease_until=NULL,
                            finished_at=?,error=NULL WHERE job_run_id=?""", (now, row["job_run_id"]))
                        return None
                    if (row["result_ref"] or delivery_states == {"pending"}) and not delivery_states.intersection(
                            ("sending", "unknown", "waiting")):
                        db.execute("""UPDATE job_runs SET status='running',lease_until=?,
                            attempts=attempts+1,started_at=?,finished_at=NULL,error=NULL
                            WHERE job_run_id=?""", (until, now, row["job_run_id"]))
                        return row["job_run_id"]
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
        from agent.scheduler.outcome import ExecutionOutcome
        outcome = success if isinstance(success, ExecutionOutcome) else None
        with self.lock, self._connect() as db:
            db.execute("""UPDATE job_runs SET status=?,lease_until=NULL,finished_at=?,error=?,retryable=?
                WHERE job_run_id=? AND owner_user_id=?""",
                (outcome.status if outcome is not None else "completed" if success else "failed", _stamp(),
                 outcome.error if outcome is not None else error,
                 int(outcome.retryable) if outcome is not None else 1, job_run_id,
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

    def list_waiting_deliveries(self, channel_type):
        with self.lock, self._connect() as db:
            rows = db.execute("""SELECT job_run_id,leg,channel_type,receiver,platform_response
                FROM job_deliveries WHERE owner_user_id=? AND status='waiting' AND channel_type=?""",
                (self._current_user(), channel_type)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["platform_response"] = (json.loads(item["platform_response"])
                                         if item["platform_response"] else None)
            result.append(item)
        return result

    def get_delivery(self, job_run_id, leg):
        with self.lock, self._connect() as db:
            row = db.execute("""SELECT * FROM job_deliveries WHERE job_run_id=? AND leg=?
                AND owner_user_id=?""", (job_run_id, leg, self._current_user())).fetchone()
        if not row:
            return None
        result = dict(row)
        result["retryable"] = bool(result["retryable"])
        result["platform_response"] = (json.loads(result["platform_response"])
                                       if result["platform_response"] else None)
        return result

    def latest_delivery(self, task_id):
        with self.lock, self._connect() as db:
            row = db.execute("""SELECT d.status,d.channel_type,d.receiver,d.error,d.updated_at
                FROM job_deliveries d JOIN job_runs r ON r.job_run_id=d.job_run_id
                WHERE r.task_id=? AND r.owner_user_id=?
                ORDER BY d.updated_at DESC,d.rowid DESC LIMIT 1""",
                (task_id, self._current_user())).fetchone()
        return dict(row) if row else None

    def queue_delivery(self, job_run_id, leg, channel_type, receiver):
        with self.lock, self._connect() as db:
            if not db.execute("SELECT 1 FROM job_runs WHERE job_run_id=? AND owner_user_id=?",
                              (job_run_id, self._current_user())).fetchone():
                raise ValueError("job run not found")
            db.execute("""INSERT OR IGNORE INTO job_deliveries
                (job_run_id,leg,owner_user_id,channel_type,receiver,status,updated_at)
                VALUES (?,?,?,?,?,'pending',?)""",
                (job_run_id, leg, self._current_user(), channel_type, receiver, _stamp()))

    def begin_delivery(self, job_run_id, leg, channel_type, receiver, max_attempts=3):
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM job_runs WHERE job_run_id=? AND owner_user_id=?",
                              (job_run_id, self._current_user())).fetchone():
                raise ValueError("job run not found")
            row = db.execute("""SELECT status,attempts,retryable,updated_at FROM job_deliveries
                WHERE job_run_id=? AND leg=? AND owner_user_id=?""",
                (job_run_id, leg, self._current_user())).fetchone()
            if row:
                if row["status"] == "sending":
                    if datetime.fromisoformat(row["updated_at"]) > datetime.now(timezone.utc) - timedelta(minutes=2):
                        return "sending"
                    db.execute("""UPDATE job_deliveries SET status='unknown',retryable=0,
                        error='Previous send outcome is unknown after restart',updated_at=?
                        WHERE job_run_id=? AND leg=?""", (_stamp(), job_run_id, leg))
                    return "unknown"
                if row["status"] not in ("pending", "failed") or (
                        row["status"] == "failed" and (not row["retryable"] or row["attempts"] >= max_attempts)):
                    return row["status"]
                db.execute("""UPDATE job_deliveries SET status='sending',attempts=attempts+1,
                    retryable=0,error=NULL,updated_at=? WHERE job_run_id=? AND leg=?""",
                    (_stamp(), job_run_id, leg))
            else:
                db.execute("""INSERT INTO job_deliveries
                    (job_run_id,leg,owner_user_id,channel_type,receiver,status,attempts,updated_at)
                    VALUES (?,?,?,?,?,'sending',1,?)""",
                    (job_run_id, leg, self._current_user(), channel_type, receiver, _stamp()))
            return "send"

    def settle_delivery(self, job_run_id, leg, status, error=""):
        """Close a desktop notification that was waiting for the client."""
        if status not in ("accepted", "failed"):
            raise ValueError("invalid delivery status")
        with self.lock, self._connect() as db:
            changed = db.execute("""UPDATE job_deliveries SET status=?,error=?,updated_at=?
                WHERE job_run_id=? AND leg=? AND owner_user_id=? AND status='waiting'""",
                (status, error or None, _stamp(), job_run_id, leg, self._current_user())).rowcount
            if not changed:
                raise ValueError("delivery is not waiting")

    def finish_delivery(self, job_run_id, leg, status, *, error=None, platform_response=None, retryable=False):
        if status not in ("accepted", "failed", "waiting", "unknown", "expired"):
            raise ValueError("invalid delivery status")
        with self.lock, self._connect() as db:
            changed = db.execute("""UPDATE job_deliveries SET status=?,error=?,platform_response=?,
                retryable=?,updated_at=? WHERE job_run_id=? AND leg=? AND owner_user_id=? AND status='sending'""",
                (status, error, json.dumps(platform_response) if platform_response else None,
                 int(retryable), _stamp(), job_run_id, leg, self._current_user())).rowcount
            if not changed:
                raise ValueError("delivery is not sending")

    def expire_delivery(self, job_run_id, leg, channel_type, receiver):
        with self.lock, self._connect() as db:
            db.execute("""INSERT OR IGNORE INTO job_deliveries
                (job_run_id,leg,owner_user_id,channel_type,receiver,status,updated_at)
                VALUES (?,?,?,?,?,'expired',?)""",
                (job_run_id, leg, self._current_user(), channel_type, receiver, _stamp()))
            db.execute("""UPDATE job_deliveries SET status='expired',retryable=0,updated_at=?
                WHERE job_run_id=? AND leg=? AND owner_user_id=?
                AND status IN ('pending','failed','waiting')""",
                (_stamp(), job_run_id, leg, self._current_user()))
