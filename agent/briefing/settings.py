"""User-scoped mailbox configuration, kept outside the briefing database."""
from __future__ import annotations

import json
import os
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


def save_mailbox(payload: dict, path: Optional[Path] = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("mailbox settings must be an object")
    target = path if path is not None else mailbox_path()
    with _settings_lock:
        settings = load_mailbox(target)
        for key in ("host", "user", "folder"):
            value = payload.get(key, settings[key])
            if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\0"):
                raise ValueError(f"{key} is required and must be a single line")
            settings[key] = value.strip()
        if "password" in payload:
            value = payload["password"]
            if not isinstance(value, str) or any(c in value for c in "\r\n\0"):
                raise ValueError("password must be a single line")
            if value:  # A blank field preserves the existing app password.
                settings["password"] = value
        if not settings["password"]:
            raise ValueError("password is required")
        port = payload.get("port", settings["port"])
        if isinstance(port, bool) or not str(port).isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        settings["port"] = int(port)
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
        return public_mailbox(settings)
