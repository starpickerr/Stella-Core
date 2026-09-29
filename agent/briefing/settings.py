"""User-scoped mailbox configuration, kept outside the briefing database."""
from __future__ import annotations

import json
import os
import ipaddress
import re
import tempfile
import threading
from pathlib import Path
from typing import Optional

_settings_lock = threading.RLock()


def mailbox_path() -> Path:
    from common.state_dir import briefing_db
    return briefing_db(ensure=False).with_name("mailbox.json")


def load_mailbox(path: Optional[Path] = None) -> dict:
    target = path if path is not None else mailbox_path()
    settings = {
        "host": os.environ.get("IMAP_HOST", "").strip(),
        "user": os.environ.get("IMAP_USER", "").strip(),
        "password": os.environ.get("IMAP_PASSWORD", ""),
        "port": os.environ.get("IMAP_PORT", "") or 993,
        "folder": os.environ.get("IMAP_FOLDER", "").strip() or "INBOX",
    }
    with _settings_lock:
        if target.exists():
            saved = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("invalid mailbox settings")
            settings.update({key: saved[key] for key in settings if key in saved})
    return settings


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
    }


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
    settings = load_mailbox(path)
    settings["host"] = normalize_imap_host(payload.get("host", settings["host"]))
    for key, label in (("user", "邮箱账号"), ("folder", "邮件文件夹")):
        value = payload.get(key, settings[key])
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\0"):
            raise ValueError(f"请填写有效的{label}")
        settings[key] = value.strip()
    value = payload.get("password", "")
    if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
        raise ValueError("授权码格式不正确，请检查是否包含换行")
    if value:
        settings["password"] = value
    if not settings["password"] or not settings["password"].strip():
        raise ValueError("请填写邮箱授权码")
    port = payload.get("port", settings["port"])
    if isinstance(port, bool) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("SSL 端口必须是 1 至 65535 的整数")
    settings["port"] = int(port)
    return settings


def check_mailbox_connection(payload: dict, path: Optional[Path] = None) -> None:
    """Read-only login/folder check. Testing a draft does not save it."""
    from agent.briefing.sources.email import EmailSource
    settings = resolve_mailbox(payload, path)
    EmailSource(**settings).check_connection()


def save_mailbox(payload: dict, path: Optional[Path] = None) -> dict:
    target = path if path is not None else mailbox_path()
    with _settings_lock:
        settings = resolve_mailbox(payload, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".mailbox-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(settings, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return public_mailbox(load_mailbox(target))
