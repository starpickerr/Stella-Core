"""Resolve one user-facing working root without creating data on lookups."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil

from agent.workspace import project_store
from common.runtime_identity import current_identity
from common.state_dir import personal_work_dir

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_EXTERNAL_ID = re.compile(r"^[A-Za-z0-9_:@.-]{1,80}$")
_RESERVED = frozenset({"sessions", "shared", "automations"})


@dataclass(frozen=True)
class WorkContext:
    root: Path
    kind: str
    work_root: Path
    private_root: Path | None
    agent_id: str
    session_id: str | None
    task_id: str | None


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def private_access(path: str, context: WorkContext) -> str | None:
    """Classify reserved Work paths: read, write, deny, or outside this boundary.

    A broad project/Full Access root never overrides another conversation's
    private directory. Shared grants apply to one file, never its parent.
    """
    real = os.path.realpath(os.path.expanduser(path))
    from agent.workspace.shares import _manifest_file
    if real == os.path.realpath(_manifest_file()):
        return "deny"
    work = os.path.realpath(context.work_root)
    if not _inside(real, work):
        return None
    if real == work:
        return "deny"
    for category in ("sessions", "automations"):
        reserved = os.path.join(work, category)
        if _inside(real, reserved):
            own = os.path.realpath(context.private_root) if context.private_root else None
            if own and _inside(real, own) and _inside(own, reserved):
                return "write"
            return "deny"
    shared = os.path.join(work, "shared")
    if _inside(real, shared):
        if context.session_id and not context.task_id:
            from agent.workspace.shares import share_access
            return share_access(real, context.session_id, context.agent_id) or "deny"
        return "deny"
    return None


def _valid(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def _safe_segment(value: str | None, label: str) -> str:
    """Keep platform chat IDs stable without placing their punctuation in paths."""
    if not isinstance(value, str) or not _EXTERNAL_ID.fullmatch(value) or value in (".", ".."):
        raise ValueError(f"invalid {label}")
    if _ID.fullmatch(value):
        return value
    return "~" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:40]


def resolve_context(session_id: str | None, agent_id: str | None = None,
                    task_id: str | None = None, ensure: bool = False) -> WorkContext:
    """Use a bound project, stable task folder, or private conversation folder."""
    from agent.registry import get_agent_registry

    agent_id = _valid(get_agent_registry().default_agent_id if agent_id is None else agent_id, "agent ID")
    session_segment = _safe_segment(session_id, "session ID") if session_id is not None else None
    task_segment = _safe_segment(task_id, "task ID") if task_id is not None else None
    identity = current_identity().derive(agent_id=agent_id)
    work_root = personal_work_dir(identity=identity, ensure=False)
    private_root = (work_root / "automations" / agent_id / task_segment if task_segment else
                    work_root / "sessions" / agent_id / session_segment if session_segment else None)
    if private_root is not None:
        current = work_root
        for segment in private_root.relative_to(work_root).parts:
            current = current / segment
            if current.is_symlink():
                raise PermissionError('private Work directories cannot use symlinks')
    binding = project_store.get_project_binding(session_id, agent_id) if session_id else None
    if binding:
        project = Path(os.path.realpath(os.path.expanduser(binding)))
        if not project.is_dir():
            raise FileNotFoundError(f"bound project is unavailable: {binding}")
        return WorkContext(project, "project", work_root, private_root, agent_id, session_id, task_id)
    if private_root is not None:
        if ensure:
            private_root.mkdir(parents=True, exist_ok=True)
        return WorkContext(private_root, "automation" if task_id else "session", work_root,
                           private_root, agent_id, session_id, task_id)
    return WorkContext(work_root, "legacy", work_root, None, agent_id, None, None)


def _legacy_source(work_root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if not relative_path or path.is_absolute() or path.parts[0] in _RESERVED or ".." in path.parts:
        raise ValueError("invalid legacy file path")
    current = work_root
    for part in path.parts:
        if part in ("", "."):
            raise ValueError("invalid legacy file path")
        current = current / part
        if current.is_symlink():
            raise ValueError("legacy symlink files cannot be copied")
    if not current.is_file() or os.path.commonpath((str(current.resolve()), str(work_root.resolve()))) != str(work_root.resolve()):
        raise ValueError("legacy file is unavailable")
    return current


def list_legacy_files() -> list[str]:
    """List old Work files, excluding the new private/shared layout."""
    work_root = personal_work_dir(ensure=False)
    if not work_root.is_dir():
        return []
    rows = []
    for parent, dirs, files in os.walk(work_root, followlinks=False):
        relative = Path(parent).relative_to(work_root)
        dirs[:] = [name for name in dirs if not (relative == Path(".") and name in _RESERVED)
                   and not (Path(parent) / name).is_symlink()]
        for name in files:
            path = Path(parent) / name
            if path.is_file() and not path.is_symlink():
                rows.append(path.relative_to(work_root).as_posix())
    return sorted(rows)


def copy_legacy_file(relative_path: str, context: WorkContext) -> Path:
    """Copy one selected old file without moving or overwriting either copy."""
    source = _legacy_source(context.work_root, relative_path)
    target = context.root / relative_path
    if os.path.commonpath((str(target.parent.resolve()), str(context.root.resolve()))) != str(context.root.resolve()):
        raise ValueError("target escapes workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.commonpath((str(target.parent.resolve()), str(context.root.resolve()))) != str(context.root.resolve()):
        raise ValueError("target escapes workspace")
    with source.open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    return target
