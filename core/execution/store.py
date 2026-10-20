"""SQLite store for H0 executions — Core-owned authoritative state."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    parent_execution_id TEXT,
    attempt_id TEXT NOT NULL,
    owner_plugin_id TEXT NOT NULL,
    provider_owner_plugin_id TEXT,
    task_kind TEXT NOT NULL,
    goal TEXT NOT NULL,
    acceptance_json TEXT,
    status TEXT NOT NULL,
    summary TEXT,
    error_json TEXT,
    budget_json TEXT NOT NULL,
    workspace_lease_ref TEXT,
    workspace_path TEXT,
    grant_ref TEXT,
    policy_digest TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS execution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(execution_id) REFERENCES executions(execution_id),
    UNIQUE(execution_id, sequence)
);
CREATE INDEX IF NOT EXISTS exec_by_owner ON executions(owner_plugin_id, updated_at);
CREATE INDEX IF NOT EXISTS exec_events_by_exec ON execution_events(execution_id, sequence);
"""

TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_RECOVERY = frozenset({"queued", "running", "waiting_approval", "cancel_requested", "interrupted"})


class ExecutionStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
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

    def recover_active_to_unknown(self) -> list[str]:
        """On process start, mark in-flight rows outcome_unknown (no blind restart)."""
        now = _now()
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT execution_id FROM executions WHERE status IN ({','.join('?' * len(ACTIVE_RECOVERY))})",
                tuple(ACTIVE_RECOVERY),
            ).fetchall()
            ids = [r["execution_id"] for r in rows]
            if ids:
                db.execute(
                    f"UPDATE executions SET status='outcome_unknown', updated_at=? "
                    f"WHERE status IN ({','.join('?' * len(ACTIVE_RECOVERY))})",
                    (now, *ACTIVE_RECOVERY),
                )
                for eid in ids:
                    self._append_event_unlocked(
                        db, eid, attempt_id="", type_="recovery", payload={"to": "outcome_unknown"}
                    )
            return ids

    def insert(self, row: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO executions(
                    execution_id, parent_execution_id, attempt_id, owner_plugin_id,
                    provider_owner_plugin_id, task_kind, goal, acceptance_json, status,
                    budget_json, grant_ref, policy_digest, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["execution_id"],
                    row.get("parent_execution_id"),
                    row["attempt_id"],
                    row["owner_plugin_id"],
                    row.get("provider_owner_plugin_id"),
                    row["task_kind"],
                    row["goal"],
                    json.dumps(row.get("acceptance") or {}, ensure_ascii=False),
                    row["status"],
                    json.dumps(row["budget"], ensure_ascii=False),
                    row.get("grant_ref"),
                    row.get("policy_digest"),
                    now,
                    now,
                ),
            )
            self._append_event_unlocked(
                db, row["execution_id"], row["attempt_id"], "queued", {"status": "queued"}
            )
        return self.get(row["execution_id"])

    def get(self, execution_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM executions WHERE execution_id=?", (execution_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def list(self, *, owner_plugin_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            if owner_plugin_id:
                rows = db.execute(
                    "SELECT * FROM executions WHERE owner_plugin_id=? ORDER BY updated_at DESC LIMIT ?",
                    (owner_plugin_id, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM executions ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def update_status(
        self,
        execution_id: str,
        status: str,
        *,
        summary: str | None = None,
        error: dict | None = None,
        allow_from_terminal: bool = False,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM executions WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if row is None:
                raise KeyError(execution_id)
            current = row["status"]
            if current in TERMINAL and not allow_from_terminal:
                raise TerminalStoreConflict(current, status)
            finished = now if status in TERMINAL else None
            started = row["started_at"] or (now if status == "running" else None)
            db.execute(
                """UPDATE executions SET status=?, summary=COALESCE(?, summary),
                   error_json=?, updated_at=?, started_at=COALESCE(?, started_at),
                   finished_at=COALESCE(?, finished_at) WHERE execution_id=?""",
                (
                    status,
                    summary,
                    json.dumps(error, ensure_ascii=False) if error is not None else row["error_json"],
                    now,
                    started,
                    finished,
                    execution_id,
                ),
            )
            self._append_event_unlocked(
                db,
                execution_id,
                row["attempt_id"],
                status,
                {"status": status, "summary": summary, "error": error},
            )
        return self.get(execution_id)  # type: ignore[return-value]

    def set_cancel_requested(self, execution_id: str) -> dict[str, Any]:
        now = _now()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM executions WHERE execution_id=?", (execution_id,)
            ).fetchone()
            if row is None:
                raise KeyError(execution_id)
            if row["status"] in TERMINAL:
                raise TerminalStoreConflict(row["status"], "cancel_requested")
            db.execute(
                """UPDATE executions SET cancel_requested=1, status='cancel_requested',
                   updated_at=? WHERE execution_id=?""",
                (now, execution_id),
            )
            self._append_event_unlocked(
                db, execution_id, row["attempt_id"], "cancel_requested", {}
            )
        return self.get(execution_id)  # type: ignore[return-value]

    def attach_workspace(self, execution_id: str, lease_ref: str, path: str) -> None:
        now = _now()
        with self._lock, self._connect() as db:
            db.execute(
                """UPDATE executions SET workspace_lease_ref=?, workspace_path=?, updated_at=?
                   WHERE execution_id=?""",
                (lease_ref, path, now, execution_id),
            )

    def attach_artifacts(self, execution_id: str, refs: list[str]) -> None:
        now = _now()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT artifact_refs_json, status FROM executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise KeyError(execution_id)
            if row["status"] in TERMINAL:
                raise TerminalStoreConflict(row["status"], "attach_artifacts")
            existing = json.loads(row["artifact_refs_json"] or "[]")
            merged = list(dict.fromkeys([*existing, *refs]))
            db.execute(
                "UPDATE executions SET artifact_refs_json=?, updated_at=? WHERE execution_id=?",
                (json.dumps(merged, ensure_ascii=False), now, execution_id),
            )

    def append_event(
        self, execution_id: str, type_: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT attempt_id, status FROM executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise KeyError(execution_id)
            if row["status"] in TERMINAL:
                raise TerminalStoreConflict(row["status"], type_)
            return self._append_event_unlocked(db, execution_id, row["attempt_id"], type_, payload)

    def events(self, execution_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                """SELECT * FROM execution_events WHERE execution_id=? AND sequence>?
                   ORDER BY sequence""",
                (execution_id, after_sequence),
            ).fetchall()
            return [
                {
                    "executionId": r["execution_id"],
                    "attemptId": r["attempt_id"],
                    "sequence": r["sequence"],
                    "occurredAt": r["occurred_at"],
                    "type": r["type"],
                    "safePayload": json.loads(r["payload_json"] or "{}"),
                }
                for r in rows
            ]

    def _append_event_unlocked(
        self,
        db: sqlite3.Connection,
        execution_id: str,
        attempt_id: str,
        type_: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        seq_row = db.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS s FROM execution_events WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        sequence = int(seq_row["s"]) + 1
        if not attempt_id:
            erow = db.execute(
                "SELECT attempt_id FROM executions WHERE execution_id=?", (execution_id,)
            ).fetchone()
            attempt_id = erow["attempt_id"] if erow else ""
        occurred = _now()
        db.execute(
            """INSERT INTO execution_events(execution_id, attempt_id, sequence, occurred_at, type, payload_json)
               VALUES (?,?,?,?,?,?)""",
            (
                execution_id,
                attempt_id,
                sequence,
                occurred,
                type_,
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        return {
            "executionId": execution_id,
            "attemptId": attempt_id,
            "sequence": sequence,
            "occurredAt": occurred,
            "type": type_,
            "safePayload": payload or {},
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "executionId": row["execution_id"],
            "parentExecutionId": row["parent_execution_id"],
            "attemptId": row["attempt_id"],
            "ownerPluginId": row["owner_plugin_id"],
            "providerOwnerPluginId": row["provider_owner_plugin_id"],
            "taskKind": row["task_kind"],
            "goal": row["goal"],
            "acceptance": json.loads(row["acceptance_json"] or "{}"),
            "status": row["status"],
            "summary": row["summary"],
            "error": json.loads(row["error_json"]) if row["error_json"] else None,
            "budget": json.loads(row["budget_json"] or "{}"),
            "workspaceLeaseRef": row["workspace_lease_ref"],
            "workspacePath": row["workspace_path"],
            "grantRef": row["grant_ref"],
            "policyDigest": row["policy_digest"],
            "cancelRequested": bool(row["cancel_requested"]),
            "artifactRefs": json.loads(row["artifact_refs_json"] or "[]"),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
        }


class TerminalStoreConflict(RuntimeError):
    def __init__(self, current: str, attempted: str):
        super().__init__(f"terminal status {current!r} rejects {attempted!r}")
        self.current = current
        self.attempted = attempted
