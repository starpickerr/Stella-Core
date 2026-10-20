"""Immutable artifact sealing with content digest."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any


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
    dest_dir = store / execution_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest[:16]}-{src.name}"
    if not dest.exists():
        shutil.copy2(src, dest)
    artifact_id = uuid.uuid4().hex[:16]
    return {
        "artifactRef": f"artifact:{artifact_id}",
        "sha256": digest,
        "path": str(dest),
        "name": src.name,
        "executionId": execution_id,
    }
