"""Explicit, exact-file grants for copies under the user's Work/shared folder."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import uuid

from agent.workspace.context import resolve_context
from common.state_dir import user_root

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_lock = threading.RLock()


def _manifest_file() -> Path:
    return user_root() / "work_shares.json"


def _identity(session_id: str, agent_id: str) -> tuple[str, str]:
    if not isinstance(agent_id, str) or not _ID.fullmatch(agent_id):
        raise ValueError("invalid agent ID")
    if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
        raise ValueError("invalid session ID")
    return agent_id, session_id


def _load() -> dict:
    path = _manifest_file()
    if not path.exists():
        return {"version": 0, "shares": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("version"), int) or not isinstance(data.get("shares"), dict):
            raise ValueError("invalid share manifest")
        return data
    except (OSError, ValueError) as exc:
        raise ValueError("share manifest is unavailable") from exc


def _save(data: dict) -> None:
    path = _manifest_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def grant_version() -> int:
    with _lock:
        return _load()["version"]


def _regular_source(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or os.path.isabs(relative_path):
        raise ValueError("choose a relative workspace file")
    parts = Path(relative_path).parts
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid share file path")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink files cannot be shared")
    if os.path.commonpath((str(current.resolve()), str(root.resolve()))) != str(root.resolve()):
        raise ValueError("file escapes workspace")
    try:
        metadata = current.stat()
    except OSError as exc:
        raise ValueError("file is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("choose one regular file")
    if metadata.st_size > 64 * 1024 * 1024:
        raise ValueError("file is too large to share")
    return current


def create_share(owner_session: str, agent_id: str, relative_path: str,
                 recipient_session: str, access: str) -> dict:
    agent_id, owner_session = _identity(owner_session, agent_id)
    _identity(recipient_session, agent_id)
    if owner_session == recipient_session:
        raise ValueError("choose another conversation")
    if access not in ("read", "write"):
        raise ValueError("invalid share access")
    context = resolve_context(owner_session, agent_id)
    source = _regular_source(context.root, relative_path)
    shared_root = context.work_root / "shared"
    if shared_root.is_symlink():
        raise ValueError("shared folder is not trusted")
    shared_root.mkdir(parents=True, exist_ok=True)
    if os.path.commonpath((str(shared_root.resolve()), str(context.work_root.resolve()))) != str(context.work_root.resolve()):
        raise ValueError("shared folder escapes Work")
    share_id = uuid.uuid4().hex
    folder = shared_root / share_id
    folder.mkdir()
    destination = folder / source.name
    try:
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
        row = {"id": share_id, "path": str(destination), "name": source.name,
               "owner_agent": agent_id, "owner_session": owner_session,
               "recipient_session": recipient_session, "access": access, "active": True}
        with _lock:
            data = _load()
            data["shares"][share_id] = row
            data["version"] += 1
            _save(data)
        return dict(row)
    except Exception:
        shutil.rmtree(folder)
        raise


def list_shares(session_id: str, agent_id: str) -> list[dict]:
    agent_id, session_id = _identity(session_id, agent_id)
    with _lock:
        rows = _load()["shares"].values()
        return [dict(row) for row in rows if row.get("owner_agent") == agent_id and
                (row.get("owner_session") == session_id or
                 row.get("active") and row.get("recipient_session") == session_id)]


def revoke_share(share_id: str, owner_session: str, agent_id: str) -> dict:
    agent_id, owner_session = _identity(owner_session, agent_id)
    with _lock:
        data = _load()
        row = data["shares"].get(share_id)
        if not row:
            raise ValueError("share not found")
        if row.get("owner_agent") != agent_id or row.get("owner_session") != owner_session:
            raise PermissionError("only the owner can revoke this share")
        if row.get("active"):
            row["active"] = False
            data["version"] += 1
            _save(data)
        return dict(row)


def share_access(path: str, session_id: str, agent_id: str) -> str | None:
    """Return an exact file grant; callers must still apply tool permissions."""
    agent_id, session_id = _identity(session_id, agent_id)
    real = os.path.realpath(path)
    with _lock:
        for row in _load()["shares"].values():
            if row.get("owner_agent") != agent_id or os.path.realpath(row.get("path", "")) != real:
                continue
            if row.get("owner_session") == session_id:
                return "write"
            if row.get("active") and row.get("recipient_session") == session_id:
                return row.get("access")
    return None
