"""Local package install transaction stages (P2a)."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.plugins.manifest import load_manifest


class PackageStage(str, Enum):
    STAGED = "staged"
    VERIFIED = "verified"
    PREPARED = "prepared"
    COMMITTED = "committed"
    FAILED = "failed"


@dataclass
class PackageOperation:
    operation_id: str
    plugin_id: str
    version: str
    digest: str
    stage: PackageStage
    source_path: str
    target_path: str | None = None
    error: str | None = None
    history: list[str] = field(default_factory=list)


class PackageStore:
    """stage → inspect → prepare → commit with crash-safe stage markers."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.staging = self.root / "staging"
        self.packages = self.root / "packages"
        self.ops_dir = self.root / "management" / "operations"
        self.staging.mkdir(parents=True, exist_ok=True)
        self.packages.mkdir(parents=True, exist_ok=True)
        self.ops_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, source_dir: Path) -> PackageOperation:
        manifest = load_manifest(source_dir)
        digest = _sha256_tree(Path(source_dir))
        op_id = str(uuid.uuid4())
        staged = self.staging / op_id
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(source_dir, staged)
        op = PackageOperation(
            operation_id=op_id,
            plugin_id=manifest["id"],
            version=manifest["version"],
            digest=digest,
            stage=PackageStage.STAGED,
            source_path=str(Path(source_dir).resolve()),
            history=["staged"],
        )
        self._persist(op)
        return op

    def inspect(self, operation_id: str) -> PackageOperation:
        op = self._load(operation_id)
        staged = self.staging / operation_id
        manifest = load_manifest(staged)
        if manifest["id"] != op.plugin_id or manifest["version"] != op.version:
            return self._fail(op, "manifest identity changed after stage")
        digest = _sha256_tree(staged)
        if digest != op.digest:
            return self._fail(op, "package digest mismatch")
        op.stage = PackageStage.VERIFIED
        op.history.append("verified")
        self._persist(op)
        return op

    def prepare(self, operation_id: str) -> PackageOperation:
        op = self._load(operation_id)
        if op.stage != PackageStage.VERIFIED:
            return self._fail(op, f"prepare requires verified, have {op.stage}")
        target = self.packages / op.plugin_id / op.version / op.digest
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = self.staging / operation_id
        # Immutable content-addressed cache: never delete an existing digest tree.
        if target.exists():
            existing = _sha256_tree(target)
            if existing != op.digest:
                return self._fail(op, "immutable package path content mismatch")
        else:
            shutil.copytree(staged, target)
        op.target_path = str(target)
        op.stage = PackageStage.PREPARED
        op.history.append("prepared")
        self._persist(op)
        return op

    def commit(self, operation_id: str) -> PackageOperation:
        op = self._load(operation_id)
        if op.stage != PackageStage.PREPARED or not op.target_path:
            return self._fail(op, f"commit requires prepared, have {op.stage}")
        # Atomic pointer: current → digest
        current = self.packages / op.plugin_id / "current.json"
        current.write_text(
            json.dumps(
                {
                    "pluginId": op.plugin_id,
                    "version": op.version,
                    "digest": op.digest,
                    "path": op.target_path,
                    "operationId": op.operation_id,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        staged = self.staging / operation_id
        if staged.exists():
            shutil.rmtree(staged)
        op.stage = PackageStage.COMMITTED
        op.history.append("committed")
        self._persist(op)
        return op

    def get_operation(self, operation_id: str) -> PackageOperation:
        return self._load(operation_id)

    def current_package(self, plugin_id: str) -> dict[str, Any] | None:
        path = self.packages / plugin_id / "current.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _fail(self, op: PackageOperation, message: str) -> PackageOperation:
        op.stage = PackageStage.FAILED
        op.error = message
        op.history.append(f"failed:{message}")
        self._persist(op)
        return op

    def _persist(self, op: PackageOperation) -> None:
        path = self.ops_dir / f"{op.operation_id}.json"
        path.write_text(
            json.dumps(
                {
                    "operationId": op.operation_id,
                    "pluginId": op.plugin_id,
                    "version": op.version,
                    "digest": op.digest,
                    "stage": op.stage.value,
                    "sourcePath": op.source_path,
                    "targetPath": op.target_path,
                    "error": op.error,
                    "history": op.history,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _load(self, operation_id: str) -> PackageOperation:
        path = self.ops_dir / f"{operation_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return PackageOperation(
            operation_id=data["operationId"],
            plugin_id=data["pluginId"],
            version=data["version"],
            digest=data["digest"],
            stage=PackageStage(data["stage"]),
            source_path=data["sourcePath"],
            target_path=data.get("targetPath"),
            error=data.get("error"),
            history=list(data.get("history") or []),
        )


def _sha256_tree(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()
