"""Plugin-owned eLearning settings, credentials, sessions and sync state.

Everything lives under one host-provided data directory (``dataDir``). The
layout matches the pre-plugin briefing directory so a legacy directory can be
adopted as-is or copied in by ``import_legacy``.

    elearning.json                    settings (password/token stay here)
    elearning-sessions/<account>.json saved browser cookies
    elearning-courses/<account>.json  last discovered course options
    elearning-file-sync/<account>*.json  download manifests
    elearning-cursors.json            per-account sync progress / checkpoints
    elearning-audit.jsonl             policy audit events awaiting host pickup
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

PASSWORD_MASK = "********"
DEFAULTS = {
    "enabled": False,
    "base_url": "https://elearning.fudan.edu.cn",
    "username": "",
    "password": "",
    "token": "",
    "courses": [],
    "request_interval": 0.4,
    "file_sync_enabled": False,
    "file_sync_root": "",
}

_lock = threading.RLock()


def account_id(config):
    key = config["base_url"].rstrip("/") + "|" + config["username"]
    return "canvas-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".elearning-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ElearningStore:
    def __init__(self, root):
        self.root = Path(root)

    # ----- paths -------------------------------------------------------
    @property
    def settings_path(self):
        return self.root / "elearning.json"

    def session_path(self, config):
        return self.root / "elearning-sessions" / (account_id(config) + ".json")

    def course_options_path(self, config):
        return self.root / "elearning-courses" / (account_id(config) + ".json")

    def file_sync_manifest_path(self, config):
        return self.root / "elearning-file-sync" / (account_id(config) + ".json")

    @property
    def cursors_path(self):
        return self.root / "elearning-cursors.json"

    @property
    def audit_path(self):
        return self.root / "elearning-audit.jsonl"

    # ----- audit -------------------------------------------------------
    def record_audit(self, **event):
        """Queue a policy audit event; the host drains and records it."""
        event["ts"] = time.time()
        with _lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def drain_audit(self):
        with _lock:
            try:
                lines = self.audit_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
            self.audit_path.unlink(missing_ok=True)
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        return events

    # ----- session / course options -----------------------------------
    def save_session(self, config, data):
        with _lock:
            write_json(self.session_path(config), data)

    def has_credentials(self, cfg):
        return bool(cfg["password"] or cfg["token"] or self.session_path(cfg).is_file())

    def load_course_options(self, config):
        try:
            rows = json.loads(self.course_options_path(config).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)
                and isinstance(row.get("id"), str) and isinstance(row.get("name"), str)]

    def save_course_options(self, config, options):
        with _lock:
            write_json(self.course_options_path(config), options)

    # ----- cursors -----------------------------------------------------
    def get_cursors(self, config=None):
        cfg = config if config is not None else self.load_settings()
        try:
            data = json.loads(self.cursors_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        rows = data.get(account_id(cfg)) if isinstance(data, dict) else None
        return {str(k): str(v) for k, v in rows.items()} if isinstance(rows, dict) else {}

    def set_cursors(self, cursors, config=None):
        if not isinstance(cursors, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in cursors.items()
        ):
            raise ValueError("cursors 必须是字符串键值对象")
        cfg = config if config is not None else self.load_settings()
        with _lock:
            try:
                data = json.loads(self.cursors_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            merged = dict(data.get(account_id(cfg)) or {})
            merged.update(cursors)
            data[account_id(cfg)] = merged
            write_json(self.cursors_path, data)
        return dict(merged)

    # ----- settings ----------------------------------------------------
    def load_settings(self):
        with _lock:
            path = self.settings_path
            saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            if not isinstance(saved, dict):
                raise ValueError("eLearning 设置格式无效")
            return {**DEFAULTS, **saved}

    def public_settings(self, config=None):
        cfg = config if config is not None else self.load_settings()
        return {
            "enabled": cfg["enabled"], "base_url": cfg["base_url"], "username": cfg["username"],
            "courses": cfg["courses"], "course_options": self.load_course_options(cfg),
            "password_set": bool(cfg["password"]),
            "password_masked": PASSWORD_MASK if cfg["password"] else "",
            "configured": bool(cfg["username"] and cfg["courses"] and self.has_credentials(cfg)),
            "account_id": account_id(cfg),
            "file_sync_enabled": bool(cfg["file_sync_enabled"]), "file_sync_root": cfg["file_sync_root"],
        }

    def resolve_settings(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("eLearning 设置必须是对象")
        old = self.load_settings()
        cfg = {**old, **{key: payload[key] for key in ("enabled", "base_url", "username", "courses",
                                                       "file_sync_enabled", "file_sync_root") if key in payload}}
        if not isinstance(cfg["enabled"], bool):
            raise ValueError("enabled 必须是布尔值")
        if not isinstance(cfg["base_url"], str):
            raise ValueError("请填写 eLearning HTTPS 地址")
        cfg["base_url"] = cfg["base_url"].strip().rstrip("/")
        url = urlparse(cfg["base_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("eLearning 地址必须是不含账号密码的 HTTPS 地址")
        if not isinstance(cfg["username"], str) or not cfg["username"].strip():
            raise ValueError("请填写 eLearning 学工号")
        cfg["username"] = cfg["username"].strip()
        if not isinstance(cfg["courses"], list) or any(
            not isinstance(value, str) or not value.strip() for value in cfg["courses"]
        ):
            raise ValueError("课程必须是非空课程 ID 或课程名称的列表")
        cfg["courses"] = list(dict.fromkeys(value.strip() for value in cfg["courses"]))
        # Changing the briefing course selection must not silently expand an
        # existing Agent file-save grant. It can be re-enabled in Agent settings.
        if cfg["courses"] != old["courses"] and "file_sync_enabled" not in payload:
            cfg["file_sync_enabled"] = False
        if account_id(cfg) != account_id(old):
            cfg["password"] = cfg["token"] = ""
            # Never transfer an earlier account's folder grant implicitly.
            if not (payload.get("file_sync_enabled") is True and payload.get("file_sync_root")):
                cfg["file_sync_enabled"] = False
                cfg["file_sync_root"] = ""
        if not isinstance(cfg["file_sync_enabled"], bool) or not isinstance(cfg["file_sync_root"], str):
            raise ValueError("课程文件同步设置无效")
        if cfg["file_sync_enabled"]:
            if not cfg["courses"]:
                raise ValueError("请先选择允许保存文件的课程，再开启文件同步")
            if "file_sync_enabled" in payload or "file_sync_root" in payload:
                root = Path(cfg["file_sync_root"]).expanduser()
                if not root.is_dir():
                    raise ValueError("请选择已存在的保存目录；课程文件夹会自动创建")
                cfg["file_sync_root"] = str(root.resolve(strict=True))
        password = payload.get("password", "")
        if not isinstance(password, str):
            raise ValueError("eLearning 密码格式无效")
        if password and password != PASSWORD_MASK:
            cfg["password"] = password
        elif password == PASSWORD_MASK and not cfg["password"]:
            raise ValueError("请填写新账号的 eLearning 密码")
        if not cfg["password"] and not cfg["token"] and not self.session_path(cfg).is_file():
            raise ValueError("请填写 eLearning 密码")
        return cfg

    def save_settings(self, payload):
        with _lock:
            previous = self.load_settings()
            cfg = self.resolve_settings(payload)
            write_json(self.settings_path, cfg)
            if account_id(previous) != account_id(cfg):
                self.course_options_path(previous).unlink(missing_ok=True)
            if (previous.get("file_sync_enabled"), previous.get("file_sync_root")) != (
                cfg["file_sync_enabled"], cfg["file_sync_root"]
            ):
                self.record_audit(tool="elearning", operation="configure",
                                  resource=cfg["file_sync_root"] or "course files",
                                  event="file_modify", risk="L1", decision="policy_change",
                                  reason="eLearning file sync folder grant changed.")
            return self.public_settings(cfg)

    def save_file_sync_settings(self, enabled, root):
        """Manage the Agent's file-save grant without changing briefing sources."""
        if not isinstance(enabled, bool) or not isinstance(root, str):
            raise ValueError("课程文件同步设置无效")
        with _lock:
            cfg = self.load_settings()
            previous = (cfg["file_sync_enabled"], cfg["file_sync_root"])
            if enabled:
                if not cfg["username"] or not cfg["courses"] or not self.has_credentials(cfg):
                    raise ValueError("请先连接 eLearning 账号并选择课程")
                directory = Path(root).expanduser()
                if not directory.is_dir():
                    raise ValueError("请选择已存在的保存目录；课程文件夹会自动创建")
                root = str(directory.resolve(strict=True))
            cfg["file_sync_enabled"] = enabled
            cfg["file_sync_root"] = root
            write_json(self.settings_path, cfg)
            if previous != (enabled, root):
                self.record_audit(tool="elearning", operation="configure", resource=root or "course files",
                                  event="file_modify", risk="L1", decision="policy_change",
                                  reason="eLearning file sync folder grant changed.")
            return self.public_settings(cfg)

    def delete_settings(self):
        with _lock:
            cfg = self.load_settings()
            self.session_path(cfg).unlink(missing_ok=True)
            self.course_options_path(cfg).unlink(missing_ok=True)
            write_json(self.settings_path, DEFAULTS)

    # ----- legacy adoption --------------------------------------------
    def import_legacy(self, legacy_dir):
        """Copy a pre-plugin briefing directory's eLearning files once.

        Existing plugin data is never overwritten; sync cursors are not
        part of the old layout (they lived in the briefing database).
        """
        legacy = Path(legacy_dir)
        if not legacy.is_dir() or legacy.resolve() == self.root.resolve():
            return {"imported": False}
        copied = []
        pairs = [(legacy / "elearning.json", self.settings_path)]
        for sub in ("elearning-sessions", "elearning-courses", "elearning-file-sync"):
            source_dir = legacy / sub
            if source_dir.is_dir():
                pairs.extend((item, self.root / sub / item.name) for item in source_dir.iterdir() if item.is_file())
        with _lock:
            if self.settings_path.exists():
                return {"imported": False}
            for source, target in pairs:
                if source.is_file() and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    os.chmod(target, 0o600)
                    copied.append(source.name)
        return {"imported": bool(copied), "files": copied}
