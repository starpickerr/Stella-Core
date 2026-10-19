"""Load and structurally validate plugin.json (manifestVersion=1)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
_ENTRY = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))(?!.*\\)[A-Za-z0-9_./-]+\.py$")


class ManifestError(ValueError):
    pass


def load_manifest(path: Path | str) -> dict[str, Any]:
    root = Path(path)
    file = root / "plugin.json" if root.is_dir() else root
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {file}: {exc}") from exc
    validate_manifest(raw)
    return raw


def validate_manifest(data: Any) -> None:
    if not isinstance(data, dict):
        raise ManifestError("manifest must be an object")
    for key in ("manifestVersion", "id", "name", "version", "hostApi", "contributes", "permissions"):
        if key not in data:
            raise ManifestError(f"missing required field: {key}")
    if data["manifestVersion"] != 1:
        raise ManifestError("manifestVersion must be 1")
    if not isinstance(data["id"], str) or not _PLUGIN_ID.match(data["id"]):
        raise ManifestError(f"invalid plugin id: {data.get('id')!r}")
    if not isinstance(data["name"], str) or not data["name"]:
        raise ManifestError("name must be a non-empty string")
    if not isinstance(data["version"], str) or not _SEMVER.match(data["version"]):
        raise ManifestError(f"invalid version: {data.get('version')!r}")
    if not isinstance(data["hostApi"], str) or not data["hostApi"]:
        raise ManifestError("hostApi must be a non-empty string")
    contributes = data["contributes"]
    if not isinstance(contributes, dict):
        raise ManifestError("contributes must be an object")
    if not any(contributes.get(k) for k in ("services", "tools", "pages", "settings", "jobs", "mcp", "skills")):
        raise ManifestError("manifest must declare at least one contribution")
    permissions = data["permissions"]
    if not isinstance(permissions, list):
        raise ManifestError("permissions must be an array")
    runtime = data.get("runtime")
    if runtime is not None:
        if not isinstance(runtime, dict):
            raise ManifestError("runtime must be an object")
        if runtime.get("kind") != "python":
            raise ManifestError("runtime.kind must be python")
        entry = runtime.get("entry")
        if not isinstance(entry, str) or not _ENTRY.match(entry):
            raise ManifestError(f"invalid runtime.entry: {entry!r}")
        if not isinstance(runtime.get("abi"), str) or not runtime["abi"]:
            raise ManifestError("runtime.abi required")
