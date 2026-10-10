"""Resolve one user-facing working root without creating data on lookups."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil

from agent.workspace import project_store
from common.runtime_identity import current_identity
from common.state_dir import personal_work_dir

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
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


def _valid(value: str | None, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def resolve_context(session_id: str | None, agent_id: str | None = None,
                    task_id: str | None = None, ensure: bool = False) -> WorkContext:
    """Use a bound project, stable task folder, or private conversation folder."""
    from agent.registry import get_agent_registry

    agent_id = _valid(get_agent_registry().default_agent_id if agent_id is None else agent_id, "agent ID")
    if session_id is not None:
        _valid(session_id, "session ID")
    if task_id is not None:
        _valid(task_id, "task ID")
    identity = current_identity().derive(agent_id=agent_id)
    work_root = personal_work_dir(identity=identity, ensure=False)
    private_root = (work_root / "automations" / agent_id / task_id if task_id else
                    work_root / "sessions" / agent_id / session_id if session_id else None)
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
