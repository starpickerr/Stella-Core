"""Task-rule persistence over the shared ``automation.db`` ``tasks`` table.

Only task rows are touched. Occurrence leases, deliveries and the legacy
tasks.json migration belong to Core's AutomationStore and are never opened here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

_SCHEMA = Path(__file__).with_name("schema.sql")


class TaskRuleStore:
    def __init__(self, db_path: Path, agent_id: str, user_id: str = ""):
        if not agent_id:
            raise ValueError("agentId is required")
        self.db_path = Path(db_path)
        self.agent_id = agent_id
        self.user_id = user_id or ""
        self.lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA.read_text(encoding="utf-8"))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
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

    def _write(self, db, task_id: str, task: dict) -> None:
        data = dict(task)
        data["id"] = task_id
        data["owner_agent_id"] = data.get("owner_agent_id") or self.agent_id
        data["owner_user_id"] = data.get("owner_user_id") or ""
        if data["owner_agent_id"] != self.agent_id:
            raise ValueError("Task belongs to a different Agent")
        db.execute(
            """INSERT INTO tasks(task_id,owner_agent_id,owner_user_id,enabled,next_run_at,data)
            VALUES (?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET
            owner_user_id=excluded.owner_user_id,enabled=excluded.enabled,
            next_run_at=excluded.next_run_at,data=excluded.data""",
            (task_id, self.agent_id, data["owner_user_id"], int(data.get("enabled", True)),
             data.get("next_run_at"), json.dumps(data, ensure_ascii=False)))

    def add(self, task: dict) -> dict:
        task_id = task.get("id")
        if not task_id:
            raise ValueError("Task must have an 'id' field")
        if task.get("owner_user_id") not in (None, "", self.user_id):
            raise ValueError("Task belongs to a different user")
        task = dict(task, owner_user_id=self.user_id)
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM tasks WHERE task_id=?", (task_id,)).fetchone():
                raise ValueError(f"Task with id '{task_id}' already exists")
            self._write(db, task_id, task)
        return task

    def get(self, task_id: str) -> dict | None:
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT data FROM tasks WHERE task_id=? AND owner_agent_id=? AND owner_user_id=?",
                (task_id, self.agent_id, self.user_id)).fetchone()
            return json.loads(row[0]) if row else None

    def list(self, enabled_only: bool = False) -> list[dict]:
        with self.lock, self._connect() as db:
            rows = db.execute("SELECT data FROM tasks WHERE owner_agent_id=? AND owner_user_id=?",
                              (self.agent_id, self.user_id)).fetchall()
        tasks = [json.loads(row[0]) for row in rows]
        if enabled_only:
            tasks = [task for task in tasks if task.get("enabled", True)]
        return sorted(tasks, key=lambda task: (not task.get("enabled", True),
                                              task.get("next_run_at") or "9999-12-31"))

    def update(self, task_id: str, updates: dict[str, Any]) -> dict:
        if "owner_user_id" in updates or "owner_agent_id" in updates:
            raise ValueError("Task ownership cannot be changed")
        with self.lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM tasks WHERE task_id=? AND owner_agent_id=? AND owner_user_id=?",
                (task_id, self.agent_id, self.user_id)).fetchone()
            if not row:
                raise ValueError(f"Task '{task_id}' not found")
            task = json.loads(row[0])
            for key, value in updates.items():
                if key == "run_permission_mode" and value is None:
                    task.pop(key, None)
                else:
                    task[key] = value
            task["updated_at"] = datetime.now().isoformat()
            self._write(db, task_id, task)
            return task

    def delete(self, task_id: str) -> None:
        with self.lock, self._connect() as db:
            deleted = db.execute(
                "DELETE FROM tasks WHERE task_id=? AND owner_agent_id=? AND owner_user_id=?",
                (task_id, self.agent_id, self.user_id)).rowcount
        if not deleted:
            raise ValueError(f"Task '{task_id}' not found")
