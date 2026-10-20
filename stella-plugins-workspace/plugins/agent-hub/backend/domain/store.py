"""Persistence for provider configs and external session/run mappings."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentHubStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA.read_text(encoding="utf-8"))
            self._ensure_identity_columns(db)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
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

    @staticmethod
    def _ensure_identity_columns(db: sqlite3.Connection) -> None:
        cols = {row[1] for row in db.execute("PRAGMA table_info(provider_configs)")}
        if "agent_id" not in cols:
            db.execute("ALTER TABLE provider_configs ADD COLUMN agent_id TEXT")
        if "access_mode" not in cols:
            db.execute("ALTER TABLE provider_configs ADD COLUMN access_mode TEXT")
        # Backfill from known provider_local_id aliases.
        mapping = {
            "codex-app-server": ("codex", "app-server"),
            "codex-cli": ("codex", "cli"),
            "cursor-acp": ("cursor", "acp"),
            "cursor-cli": ("cursor", "cli"),
            "claude-code": ("claude-code", "cli"),
        }
        for local_id, (agent_id, access_mode) in mapping.items():
            db.execute(
                """UPDATE provider_configs
                   SET agent_id=COALESCE(NULLIF(agent_id, ''), ?),
                       access_mode=COALESCE(NULLIF(access_mode, ''), ?)
                   WHERE provider_local_id=?""",
                (agent_id, access_mode, local_id),
            )

    def upsert_provider(self, row: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self.lock, self._connect() as db:
            existing = db.execute(
                "SELECT created_at FROM provider_configs WHERE provider_config_id=?",
                (row["providerConfigId"],),
            ).fetchone()
            created = existing["created_at"] if existing else now
            db.execute(
                """INSERT INTO provider_configs(
                    provider_config_id, provider_local_id, agent_id, access_mode, display_name, binary_path,
                    enabled, settings_json, last_probe_json, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider_config_id) DO UPDATE SET
                    agent_id=excluded.agent_id,
                    access_mode=excluded.access_mode,
                    display_name=excluded.display_name,
                    binary_path=excluded.binary_path,
                    enabled=excluded.enabled,
                    settings_json=excluded.settings_json,
                    last_probe_json=COALESCE(excluded.last_probe_json, provider_configs.last_probe_json),
                    updated_at=excluded.updated_at""",
                (
                    row["providerConfigId"],
                    row["providerLocalId"],
                    row.get("agentId"),
                    row.get("accessMode"),
                    row["displayName"],
                    row.get("binaryPath"),
                    int(bool(row.get("enabled", True))),
                    json.dumps(row.get("settings") or {}, ensure_ascii=False),
                    json.dumps(row["lastProbe"], ensure_ascii=False) if row.get("lastProbe") is not None else None,
                    created,
                    now,
                ),
            )
        return self.get_provider(row["providerConfigId"])  # type: ignore[return-value]

    def save_probe(self, provider_config_id: str, probe: dict[str, Any]) -> None:
        now = _now()
        with self.lock, self._connect() as db:
            db.execute(
                "UPDATE provider_configs SET last_probe_json=?, updated_at=? WHERE provider_config_id=?",
                (json.dumps(probe, ensure_ascii=False), now, provider_config_id),
            )

    def get_provider(self, provider_config_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM provider_configs WHERE provider_config_id=?",
                (provider_config_id,),
            ).fetchone()
            return self._provider_row(row) if row else None

    def list_providers(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        with self.lock, self._connect() as db:
            if enabled_only:
                rows = db.execute(
                    "SELECT * FROM provider_configs WHERE enabled=1 ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM provider_configs ORDER BY updated_at DESC"
                ).fetchall()
            return [self._provider_row(r) for r in rows]

    def delete_provider(self, provider_config_id: str) -> bool:
        with self.lock, self._connect() as db:
            cur = db.execute(
                "DELETE FROM provider_configs WHERE provider_config_id=?",
                (provider_config_id,),
            )
            return cur.rowcount > 0

    def upsert_run(self, row: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        with self.lock, self._connect() as db:
            existing = db.execute(
                "SELECT created_at FROM external_runs WHERE execution_id=?",
                (row["executionId"],),
            ).fetchone()
            created = existing["created_at"] if existing else now
            db.execute(
                """INSERT INTO external_runs(
                    execution_id, provider_config_id, external_session_ref, external_run_ref,
                    adapter_version, policy_digest, workspace_ref, status, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(execution_id) DO UPDATE SET
                    external_session_ref=excluded.external_session_ref,
                    external_run_ref=excluded.external_run_ref,
                    status=excluded.status,
                    workspace_ref=excluded.workspace_ref,
                    updated_at=excluded.updated_at""",
                (
                    row["executionId"],
                    row["providerConfigId"],
                    row.get("externalSessionRef"),
                    row.get("externalRunRef"),
                    row.get("adapterVersion"),
                    row.get("policyDigest"),
                    row.get("workspaceRef"),
                    row["status"],
                    created,
                    now,
                ),
            )
        return self.get_run(row["executionId"])  # type: ignore[return-value]

    def get_run(self, execution_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM external_runs WHERE execution_id=?", (execution_id,)
            ).fetchone()
            return self._run_row(row) if row else None

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM external_runs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._run_row(r) for r in rows]

    @staticmethod
    def _provider_row(row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "providerConfigId": row["provider_config_id"],
            "providerLocalId": row["provider_local_id"],
            "agentId": row["agent_id"] if "agent_id" in keys else None,
            "accessMode": row["access_mode"] if "access_mode" in keys else None,
            "displayName": row["display_name"],
            "binaryPath": row["binary_path"],
            "enabled": bool(row["enabled"]),
            "settings": json.loads(row["settings_json"] or "{}"),
            "lastProbe": json.loads(row["last_probe_json"]) if row["last_probe_json"] else None,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _run_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "executionId": row["execution_id"],
            "providerConfigId": row["provider_config_id"],
            "externalSessionRef": row["external_session_ref"],
            "externalRunRef": row["external_run_ref"],
            "adapterVersion": row["adapter_version"],
            "policyDigest": row["policy_digest"],
            "workspaceRef": row["workspace_ref"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
