"""Offline, copy-first migration of the legacy local user's business data."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from common.state_dir import shared_root


_USER_PATHS = ("USER.md", "MEMORY.md", "memory", "output", "bills", "briefing", "calendar", "todos", "runs", "operations.db", "health")
_MARKER = ".migration.json"


def _copy_tree(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValueError(f"cannot migrate symlink: {source}")
    if source.is_dir():
        destination.mkdir(parents=True)
        for child in source.iterdir():
            if child.name.endswith(("-wal", "-shm")):
                continue
            _copy_tree(child, destination / child.name)
    elif source.suffix == ".db":
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as old:
            with sqlite3.connect(destination) as new:
                old.backup(new)
                if new.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError(f"database verification failed: {source}")
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def migrate_local_default(root: Optional[Path] = None) -> Path:
    """Copy legacy user paths and activate the canonical path by atomic rename.

    Call only while every Stella process is stopped. The old paths are retained
    for comparison and recovery; this function never removes or rewrites them.
    """
    base = Path(root) if root is not None else shared_root()
    users = base / "users"
    target = users / "local-default"
    if (target / _MARKER).is_file():
        marker = json.loads((target / _MARKER).read_text(encoding="utf-8"))
        if marker.get("version", 1) < 2:
            old_path, new_path = base / "operations.db", target / "operations.db"
            if old_path.exists() and new_path.exists():
                with sqlite3.connect(f"file:{old_path}?mode=ro", uri=True) as old:
                    with sqlite3.connect(new_path) as new:
                        for row in old.execute("SELECT * FROM operations"):
                            existing = new.execute("SELECT * FROM operations WHERE operation_id=?", (row[0],)).fetchone()
                            if existing and existing != row:
                                raise ValueError(f"operation ledger conflict during migration: {row[0]}")
                            if not existing:
                                new.execute("INSERT INTO operations VALUES (?,?,?,?,?)", row)
            elif old_path.exists():
                _copy_tree(old_path, new_path)
            if (base / "health").exists() and not (target / "health").exists():
                _copy_tree(base / "health", target / "health")
            marker["version"] = 2
            marker["copied"] = sorted(set(marker.get("copied", [])) | {
                name for name in ("operations.db", "health") if (base / name).exists()})
            temporary = target / ".migration-v2.tmp"
            temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, target / _MARKER)
        return target
    if target.exists():
        raise FileExistsError(f"canonical user path already exists without a migration marker: {target}")
    users.mkdir(parents=True, exist_ok=True)
    staging = users / f".local-default-migration-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        copied = []
        for name in _USER_PATHS:
            source = base / name
            if source.exists() or source.is_symlink():
                _copy_tree(source, staging / name)
                copied.append(name)
        (staging / _MARKER).write_text(json.dumps({
            "version": 2, "source": str(base), "copied": copied,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target
