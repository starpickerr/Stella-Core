"""User-scoped configuration for the built-in eLearning tool and source."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from agent.briefing.settings import PASSWORD_MASK

_lock = threading.RLock()
DEFAULTS = {"enabled": False, "base_url": "https://elearning.fudan.edu.cn", "username": "",
            "password": "", "token": "", "courses": [], "request_interval": 0.4}


def settings_path():
    from common.state_dir import briefing_db
    return briefing_db(ensure=False).with_name("elearning.json")


def account_id(config):
    key = config["base_url"].rstrip("/") + "|" + config["username"]
    return "canvas-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def session_path(config):
    return settings_path().parent / "elearning-sessions" / (account_id(config) + ".json")


def course_options_path(config):
    return settings_path().parent / "elearning-courses" / (account_id(config) + ".json")


def load_course_options(config):
    try:
        rows = json.loads(course_options_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)
            and isinstance(row.get("id"), str) and isinstance(row.get("name"), str)]


def _write(path, data):
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


def save_session(config, data):
    with _lock:
        _write(session_path(config), data)


def load_settings():
    path = settings_path()
    with _lock:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(saved, dict):
            raise ValueError("eLearning 设置格式无效")
        return {**DEFAULTS, **saved}


def public_settings(config=None):
    cfg = config if config is not None else load_settings()
    auth = bool(cfg["password"] or cfg["token"] or session_path(cfg).is_file())
    return {"enabled": cfg["enabled"], "base_url": cfg["base_url"], "username": cfg["username"],
            "courses": cfg["courses"], "course_options": load_course_options(cfg), "password_set": bool(cfg["password"]),
            "password_masked": PASSWORD_MASK if cfg["password"] else "",
            "configured": bool(cfg["username"] and cfg["courses"] and auth), "account_id": account_id(cfg)}


def resolve_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("eLearning 设置必须是对象")
    old = load_settings()
    cfg = {**old, **{key: payload[key] for key in ("enabled", "base_url", "username", "courses") if key in payload}}
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
    if not isinstance(cfg["courses"], list) or any(not isinstance(value, str) or not value.strip() for value in cfg["courses"]):
        raise ValueError("课程必须是非空课程 ID 或课程名称的列表")
    cfg["courses"] = list(dict.fromkeys(value.strip() for value in cfg["courses"]))
    if account_id(cfg) != account_id(old):
        cfg["password"] = cfg["token"] = ""
    password = payload.get("password", "")
    if not isinstance(password, str):
        raise ValueError("eLearning 密码格式无效")
    if password and password != PASSWORD_MASK:
        cfg["password"] = password
    elif password == PASSWORD_MASK and not cfg["password"]:
        raise ValueError("请填写新账号的 eLearning 密码")
    if not cfg["password"] and not cfg["token"] and not session_path(cfg).is_file():
        raise ValueError("请填写 eLearning 密码")
    return cfg


def save_settings(payload):
    with _lock:
        previous = load_settings()
        cfg = resolve_settings(payload)
        _write(settings_path(), cfg)
        if account_id(previous) != account_id(cfg):
            course_options_path(previous).unlink(missing_ok=True)
        return public_settings(cfg)


def delete_settings():
    with _lock:
        cfg = load_settings()
        session_path(cfg).unlink(missing_ok=True)
        course_options_path(cfg).unlink(missing_ok=True)
        _write(settings_path(), DEFAULTS)


def check_connection(payload):
    from agent.briefing.elearning.client import ensure_login
    from agent.briefing.elearning.courses import course_list
    cfg = resolve_settings(payload)
    client = ensure_login(cfg)
    options = [{"id": str(row["id"]), "name": row.get("name") if isinstance(row.get("name"), str) else ""}
               for row in course_list(client)]
    with _lock:
        _write(course_options_path(cfg), options)
    return options


def elearning_sources():
    from agent.briefing.sources.elearning import ElearningSource
    cfg = load_settings()
    # An enabled but incomplete source must fail in the actual run with a
    # useful diagnosis, rather than silently disappearing from the briefing.
    return [ElearningSource(cfg)] if cfg["enabled"] else []
