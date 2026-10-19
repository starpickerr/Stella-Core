"""Email domain service: mailbox settings, credentials, cursors, login and fetch.

The plugin owns IMAP credentials. Public views only ever carry a masked
password; the briefing pipeline asks this service to log in and fetch and never
sees connection secrets. Cursors are *proposed* by ``fetch_messages`` and only
advance when the caller commits them with ``set_cursors`` after consuming the
messages successfully.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .hosts import normalize_imap_host
from .imap import EmailSource, _selectable_folders, mailbox_key
from .schema import ensure_schema

PASSWORD_MASK = "********"
_FIELDS = ("host", "user", "password", "port", "folder")
_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_mailbox() -> dict:
    return {"host": "", "user": "", "password": "", "port": 993, "folder": "INBOX"}


def _environment_mailbox() -> dict:
    return {
        "host": os.environ.get("IMAP_HOST", "").strip(),
        "user": os.environ.get("IMAP_USER", "").strip(),
        "password": os.environ.get("IMAP_PASSWORD", ""),
        "port": os.environ.get("IMAP_PORT", "") or 993,
        "folder": os.environ.get("IMAP_FOLDER", "").strip() or "INBOX",
    }


def _mailbox_key(cfg: dict) -> tuple:
    return (cfg["host"].casefold(), cfg["user"].casefold(), str(cfg["port"]), cfg["folder"])


def public_mailbox(settings: dict) -> dict:
    cfg = settings
    missing = ["IMAP_" + key.upper() for key in ("host", "user", "password") if not cfg[key]]
    return {
        "configured": not missing,
        "missing": missing,
        "host": cfg["host"],
        "user": cfg["user"],
        "port": cfg["port"],
        "folder": cfg["folder"],
        "password_set": bool(cfg["password"]),
        "password_masked": PASSWORD_MASK if cfg["password"] else "",
        "id": cfg.get("id", ""),
        "enabled": cfg.get("enabled", True),
        "source_account_id": _source_account_id(cfg) if cfg["host"] else "",
    }


def _source_account_id(cfg: dict) -> str:
    try:
        return mailbox_key(normalize_imap_host(cfg["host"]), int(cfg["port"]), cfg["user"], cfg["folder"])
    except (ValueError, TypeError):
        return ""


class EmailService:
    def __init__(
        self,
        db_path: Path,
        *,
        legacy_mailbox_path: str | os.PathLike | None = None,
        opener: Optional[Callable[[], object]] = None,
        lookback_days: int = 2,
        authorized_resources=None, user_id=None,
    ):
        self.authorized_resources, self.user_id = authorized_resources, user_id
        self.db_path = Path(db_path)
        self._opener = opener
        self._lookback_days = lookback_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            ensure_schema(db)
        if legacy_mailbox_path:
            self._import_legacy(Path(legacy_mailbox_path))

    # ----- storage -----------------------------------------------------
    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialized(self, db) -> bool:
        return db.execute("SELECT 1 FROM email_meta WHERE key='initialized'").fetchone() is not None

    @staticmethod
    def _mark_initialized(db) -> None:
        db.execute("INSERT OR REPLACE INTO email_meta(key,value) VALUES('initialized','1')")

    def _import_legacy(self, path: Path) -> None:
        """Adopt a pre-plugin ``mailbox.json`` exactly once."""
        with _lock, self._connect() as db:
            if self._initialized(db) or not path.is_file():
                return
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("invalid mailbox settings")
            if "mailboxes" not in saved:
                rows = [{"id": "legacy", "enabled": saved.get("enabled", True),
                         **_empty_mailbox(), **{k: saved[k] for k in _FIELDS if k in saved}}]
            else:
                raw = saved["mailboxes"]
                if not isinstance(raw, list) or any(
                    not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"] for r in raw
                ) or len({r["id"] for r in raw}) != len(raw):
                    raise ValueError("invalid mailbox settings")
                rows = [{"id": r["id"], "enabled": r.get("enabled", True), **_empty_mailbox(),
                         **{k: r[k] for k in _FIELDS if k in r}} for r in raw]
            for position, row in enumerate(rows):
                self._insert(db, row, position)
            self._mark_initialized(db)

    @staticmethod
    def _insert(db, row: dict, position: int) -> None:
        stamp = _now()
        db.execute(
            "INSERT INTO email_accounts(id,enabled,host,user,password,port,folder,position,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (row["id"], 1 if row.get("enabled", True) else 0, row["host"], row["user"],
             row["password"], int(row["port"]), row["folder"], position, stamp, stamp),
        )

    def _load_accounts(self, db=None) -> list[dict]:
        def read(conn):
            rows = conn.execute("SELECT * FROM email_accounts ORDER BY position, created_at").fetchall()
            if not rows and not self._initialized(conn):
                cfg = _environment_mailbox()
                if any(cfg[key] for key in ("host", "user", "password")):
                    return [{"id": "environment", "enabled": True, **cfg}]
                return []
            return [{"id": r["id"], "enabled": bool(r["enabled"]), "host": r["host"], "user": r["user"],
                     "password": r["password"], "port": r["port"], "folder": r["folder"]} for r in rows]
        if db is not None:
            return read(db)
        with self._connect() as conn:
            return read(conn)

    def _account(self, account_id: str, db=None) -> dict:
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("邮箱 ID 无效")
        for row in self._load_accounts(db):
            if row["id"] == account_id:
                if self.authorized_resources is not None:
                    allowed = {(ref['kind'], ref['id']) for ref in self.authorized_resources}
                    if (('user', self.user_id) not in allowed and
                            ('folder', _source_account_id(row)) not in allowed):
                        raise PermissionError('actual mailbox folder is outside the approved resource scope')
                return row
        raise KeyError("邮箱不存在，请重新打开设置")

    # ----- settings ----------------------------------------------------
    def list_accounts(self) -> dict:
        rows = [public_mailbox(row) for row in self._load_accounts()]
        configured = any(row["configured"] for row in rows)
        return {"mailboxes": rows, "configured": configured,
                "missing": [] if configured else ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"]}

    def get_account(self, account_id: str) -> dict:
        return public_mailbox(self._account(account_id))

    def list_sources(self) -> list[dict]:
        """Enabled, configured mailboxes as briefing sources (no secrets)."""
        return [
            {"id": "email:" + public["source_account_id"], "source": "email",
             "account_id": public["source_account_id"], "mailbox_id": row["id"],
             "name": f"email ({row['user']})"}
            for row in self._load_accounts()
            if row["enabled"] and (public := public_mailbox(row))["configured"]
        ]

    def _selected(self, payload: dict, rows: list) -> Optional[dict]:
        action = payload.get("action", "save")
        if action not in ("save", "add"):
            raise ValueError("invalid mailbox action")
        if action == "add":
            return None
        account_id = payload.get("id")
        if account_id is not None:
            if not isinstance(account_id, str) or not account_id:
                raise ValueError("邮箱 ID 无效")
            for row in rows:
                if row["id"] == account_id:
                    return row
            raise ValueError("邮箱不存在，请重新打开设置")
        return rows[0] if rows else None

    def _resolve(self, payload: dict, db=None) -> dict:
        """Validate a draft over saved settings; a blank password keeps the saved one."""
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        rows = self._load_accounts(db)
        existing = self._selected(payload, rows)
        settings = {key: existing[key] for key in _FIELDS} if existing else _empty_mailbox()
        settings["enabled"] = payload.get("enabled", existing.get("enabled", True) if existing else True)
        if not isinstance(settings["enabled"], bool):
            raise ValueError("enabled 必须是布尔值")
        settings["host"] = normalize_imap_host(payload.get("host", settings["host"]))
        for key, label in (("user", "邮箱账号"), ("folder", "邮件文件夹")):
            value = payload.get(key, settings[key])
            if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\0"):
                raise ValueError(f"请填写有效的{label}")
            settings[key] = value.strip()
        value = payload.get("password", "")
        if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
            raise ValueError("授权码格式不正确，请检查是否包含换行")
        if value == PASSWORD_MASK:
            if not settings["password"]:
                raise ValueError("请填写邮箱授权码")
        elif value:
            settings["password"] = value
        if not settings["password"] or not settings["password"].strip():
            raise ValueError("请填写邮箱授权码")
        port = payload.get("port", settings["port"])
        if isinstance(port, bool) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("SSL 端口必须是 1 至 65535 的整数")
        settings["port"] = int(port)
        return settings

    def save_account(self, payload: dict) -> dict:
        with _lock, self._connect() as db:
            settings = self._resolve(payload, db)
            rows = self._load_accounts(db)
            existing = self._selected(payload, rows)
            account_id = existing["id"] if existing else str(uuid.uuid4())
            key = _mailbox_key(settings)
            if any(row["id"] != account_id and _mailbox_key(row) == key for row in rows):
                raise ValueError("此邮箱和文件夹已经添加")
            saved = {"id": account_id, **settings}
            if existing and existing["id"] != "environment":
                db.execute(
                    "UPDATE email_accounts SET enabled=?,host=?,user=?,password=?,port=?,folder=?,updated_at=?"
                    " WHERE id=?",
                    (1 if saved["enabled"] else 0, saved["host"], saved["user"], saved["password"],
                     saved["port"], saved["folder"], _now(), account_id),
                )
            else:
                # First write detaches from environment defaults (old file semantics).
                persisted = [r for r in rows if r["id"] != "environment"]
                if existing and existing["id"] == "environment":
                    self._insert(db, saved, len(persisted))
                else:
                    position = db.execute("SELECT COALESCE(MAX(position),-1)+1 FROM email_accounts").fetchone()[0]
                    self._insert(db, saved, position)
            self._mark_initialized(db)
            return public_mailbox(saved)

    def delete_account(self, account_id: str) -> dict:
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("邮箱 ID 无效")
        with _lock, self._connect() as db:
            rows = self._load_accounts(db)
            existing = self._selected({"id": account_id}, rows)
            db.execute("DELETE FROM email_accounts WHERE id=?", (existing["id"],))
            self._mark_initialized(db)
        return {"deleted": True, "id": existing["id"]}

    # ----- connection --------------------------------------------------
    def _source(self, settings: dict, **extra) -> EmailSource:
        return EmailSource(
            **{key: settings[key] for key in _FIELDS},
            opener=self._opener, lookback_days=extra.pop("lookback_days", self._lookback_days), **extra,
        )

    def test_connection(self, payload: dict) -> dict:
        """Read-only login/folder check. Testing a draft does not save it."""
        settings = self._resolve(payload)
        return self._source(settings).check_connection()

    def list_folders(self, account_id: str | None = None, payload: dict | None = None) -> dict:
        """List selectable IMAP folders for a saved account or an unsaved draft."""
        if account_id is not None and payload is not None:
            raise ValueError("account_id 与 payload 只能二选一")
        if account_id is not None:
            settings = {key: self._account(account_id)[key] for key in _FIELDS}
        elif payload is not None:
            settings = self._resolve(payload)
        else:
            raise ValueError("请提供 account_id 或 payload")
        source = self._source(settings)
        client = source._connect()
        try:
            return {"folders": _selectable_folders(client), "selected": settings["folder"]}
        finally:
            try:
                client.logout()
            except Exception:
                pass

    # ----- cursors -----------------------------------------------------
    def _source_id(self, account_id: str) -> str:
        row = self._account(account_id)
        source_id = _source_account_id(row)
        if not source_id:
            raise ValueError("邮箱设置不完整，无法确定游标范围")
        return source_id

    def get_cursors(self, account_id: str) -> dict:
        source_id = self._source_id(account_id)
        with self._connect() as db:
            return {r["cursor_key"]: r["cursor_value"] for r in db.execute(
                "SELECT cursor_key,cursor_value FROM email_cursors WHERE source_account_id=?", (source_id,))}

    def set_cursors(self, account_id: str, cursors: dict) -> dict:
        if not isinstance(cursors, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str) for k, v in cursors.items()
        ):
            raise ValueError("cursors 必须是字符串键值对象")
        source_id = self._source_id(account_id)
        with _lock, self._connect() as db:
            for key, value in cursors.items():
                db.execute(
                    "INSERT INTO email_cursors(source_account_id,cursor_key,cursor_value,updated_at)"
                    " VALUES(?,?,?,?) ON CONFLICT(source_account_id,cursor_key)"
                    " DO UPDATE SET cursor_value=excluded.cursor_value, updated_at=excluded.updated_at",
                    (source_id, key, value, _now()),
                )
        return self.get_cursors(account_id)

    def reset_cursors(self, account_id: str) -> dict:
        source_id = self._source_id(account_id)
        with _lock, self._connect() as db:
            db.execute("DELETE FROM email_cursors WHERE source_account_id=?", (source_id,))
        return {"reset": True, "account_id": account_id}

    # ----- fetch -------------------------------------------------------
    def fetch_messages(
        self,
        account_id: str,
        since: str | None = None,
        until: str | None = None,
        cursors: dict | None = None,
        refresh_existing_content: bool = False,
        lookback_days: int | None = None,
    ) -> dict:
        row = self._account(account_id)
        if not row["enabled"]:
            raise ValueError("邮箱未启用")
        if not public_mailbox(row)["configured"]:
            raise ValueError("邮箱设置不完整，请先配置 IMAP 地址、账号与授权码")
        if lookback_days is not None and (
            isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or not 1 <= lookback_days <= 365
        ):
            raise ValueError("lookback_days 必须是 1 至 365 的整数")
        source = self._source({key: row[key] for key in _FIELDS},
                              **({"lookback_days": lookback_days} if lookback_days else {}))
        merged = dict(self.get_cursors(account_id) if cursors is None else cursors)
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in merged.items()):
            raise ValueError("cursors 必须是字符串键值对象")
        if since is not None:
            merged["since"] = since
        if until is not None:
            merged["until"] = until
        if refresh_existing_content:
            merged["refresh_existing_content"] = "1"
        result = source.fetch(merged)
        return {
            "source": source.name,
            "account_id": source.account_id,
            "mailbox_id": row["id"],
            "items": [item.to_catalog_payload() for item in result.items],
            "cursors": dict(result.cursors),
            "errors": list(result.errors),
        }
