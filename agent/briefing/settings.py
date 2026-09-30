"""User-scoped mailbox configuration, kept outside the briefing database."""
from __future__ import annotations

import json
import os
import ipaddress
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

_settings_lock = threading.RLock()
PASSWORD_MASK = "********"
_MAILBOX_FIELDS = ("host", "user", "password", "port", "folder")


def mailbox_path() -> Path:
    from common.state_dir import briefing_db
    return briefing_db(ensure=False).with_name("mailbox.json")


def _environment_mailbox() -> dict:
    return {
        "host": os.environ.get("IMAP_HOST", "").strip(),
        "user": os.environ.get("IMAP_USER", "").strip(),
        "password": os.environ.get("IMAP_PASSWORD", ""),
        "port": os.environ.get("IMAP_PORT", "") or 993,
        "folder": os.environ.get("IMAP_FOLDER", "").strip() or "INBOX",
    }


def _empty_mailbox() -> dict:
    return {"host": "", "user": "", "password": "", "port": 993, "folder": "INBOX"}


def load_mailboxes(path: Optional[Path] = None) -> list:
    """Read all accounts; legacy single-account files migrate on the next save."""
    target = path if path is not None else mailbox_path()
    with _settings_lock:
        if not target.exists():
            cfg = _environment_mailbox()
            return [{"id": "environment", "enabled": True, **cfg}] if any(cfg[key] for key in ("host", "user", "password")) else []
        saved = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("invalid mailbox settings")
        if "mailboxes" not in saved:
            cfg = _environment_mailbox()
            cfg.update({key: saved[key] for key in _MAILBOX_FIELDS if key in saved})
            return [{"id": "legacy", "enabled": saved.get("enabled", True), **cfg}]
        rows = saved["mailboxes"]
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows
        ) or len({row["id"] for row in rows}) != len(rows):
            raise ValueError("invalid mailbox settings")
        return [{"id": row["id"], "enabled": row.get("enabled", True), **_empty_mailbox(), **{
            key: row[key] for key in _MAILBOX_FIELDS if key in row
        }} for row in rows]


def load_mailbox(path: Optional[Path] = None) -> dict:
    """Compatibility for a directly constructed EmailSource: use the first account."""
    rows = load_mailboxes(path)
    return {key: rows[0][key] for key in _MAILBOX_FIELDS} if rows else _empty_mailbox()


def public_mailbox(settings: Optional[dict] = None) -> dict:
    cfg = settings if settings is not None else load_mailbox()
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
    }


def public_mailboxes(path: Optional[Path] = None) -> dict:
    rows = [public_mailbox(row) for row in load_mailboxes(path)]
    configured = any(row["configured"] for row in rows)
    return {"mailboxes": rows, "configured": configured,
            "missing": [] if configured else ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"]}


def email_sources(path: Optional[Path] = None) -> list:
    """Use the same account factory for manual, scheduled and tool generation."""
    from agent.briefing.sources.email import EmailSource
    return [EmailSource(**{key: row[key] for key in _MAILBOX_FIELDS})
            for row in load_mailboxes(path) if row["enabled"] and public_mailbox(row)["configured"]]


def normalize_imap_host(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("请填写 IMAP 服务器地址")
    host = value.strip()
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        encoded = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        encoded = ""
    if not encoded or len(encoded) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in encoded.split(".")
    ):
        raise ValueError("IMAP 服务器只填写主机名，例如 imap.gmail.com；不要填写邮箱地址、网址或端口")
    return encoded


def resolve_mailbox(payload: dict, path: Optional[Path] = None) -> dict:
    """Validate a draft over saved settings; a blank password keeps the saved one."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    rows = load_mailboxes(path)
    existing = _selected_mailbox(payload, rows)
    settings = {key: existing[key] for key in _MAILBOX_FIELDS} if existing else _empty_mailbox()
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


def _selected_mailbox(payload: dict, rows: list) -> Optional[dict]:
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


def check_mailbox_connection(payload: dict, path: Optional[Path] = None) -> dict:
    """Read-only login/folder check. Testing a draft does not save it."""
    from agent.briefing.sources.email import EmailSource
    settings = resolve_mailbox(payload, path)
    return EmailSource(**{key: settings[key] for key in _MAILBOX_FIELDS}).check_connection()


def save_mailbox(payload: dict, path: Optional[Path] = None) -> dict:
    target = path if path is not None else mailbox_path()
    with _settings_lock:
        settings = resolve_mailbox(payload, target)
        rows = load_mailboxes(target)
        existing = _selected_mailbox(payload, rows)
        account_id = existing["id"] if existing else str(uuid.uuid4())
        key = _mailbox_key(settings)
        if any(row["id"] != account_id and _mailbox_key(row) == key for row in rows):
            raise ValueError("此邮箱和文件夹已经添加")
        saved = {"id": account_id, **settings}
        if existing:
            rows = [saved if row["id"] == account_id else row for row in rows]
        else:
            rows.append(saved)
        _write_mailboxes(target, rows)
        return public_mailbox(saved)


def _mailbox_key(cfg: dict) -> tuple:
    return (cfg["host"].casefold(), cfg["user"].casefold(), str(cfg["port"]), cfg["folder"])


def delete_mailbox(account_id: str, path: Optional[Path] = None) -> None:
    if not isinstance(account_id, str) or not account_id:
        raise ValueError("邮箱 ID 无效")
    target = path if path is not None else mailbox_path()
    with _settings_lock:
        rows = load_mailboxes(target)
        existing = _selected_mailbox({"id": account_id}, rows)
        _write_mailboxes(target, [row for row in rows if row["id"] != existing["id"]])


def _write_mailboxes(target: Path, rows: list) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".mailbox-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump({"version": 2, "mailboxes": rows}, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
