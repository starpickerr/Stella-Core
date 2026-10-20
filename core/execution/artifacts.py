"""Immutable artifact sealing with content digest."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from core.execution.paths import managed_child


def seal_artifact(
    *,
    store_root: Path,
    source_path: Path | str,
    execution_id: str,
) -> dict[str, Any]:
    src = Path(source_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    store = Path(store_root).resolve()
    dest_dir = managed_child(store, execution_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest[:16]}-{src.name}"
    if not dest.resolve().is_relative_to(dest_dir):
        raise PermissionError("artifact destination escapes managed store")
    if not dest.exists():
        shutil.copy2(src, dest)
        dest.chmod(0o444)
    if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
        raise ValueError("sealed artifact digest mismatch")
    artifact_id = uuid.uuid4().hex[:16]
    artifact = {
        "artifactRef": f"artifact:{artifact_id}",
        "sha256": digest,
        "path": str(dest),
        "name": src.name,
        "executionId": execution_id,
    }
    with tempfile.NamedTemporaryFile(mode="w", dir=dest_dir, encoding="utf-8", delete=False) as handle:
        json.dump(artifact, handle)
        temporary = Path(handle.name)
    os.replace(temporary, dest_dir / f"{artifact_id}.json")
    return artifact


def resolve_artifact(*, store_root: Path, execution_id: str, artifact_ref: str) -> dict[str, Any]:
    match = re.fullmatch(r"artifact:([a-f0-9]{16})", artifact_ref)
    if not match:
        raise ValueError("invalid artifact reference")
    directory = managed_child(store_root, execution_id)
    manifest = directory / f"{match[1]}.json"
    if not manifest.resolve().is_relative_to(directory):
        raise PermissionError("artifact manifest escapes managed store")
    artifact = json.loads(manifest.read_text(encoding="utf-8"))
    target = Path(artifact["path"]).resolve()
    if artifact.get("executionId") != execution_id or not target.is_relative_to(directory):
        raise PermissionError("artifact belongs to another execution")
    if hashlib.sha256(target.read_bytes()).hexdigest() != artifact["sha256"]:
        raise ValueError("sealed artifact digest mismatch")
    return artifact
