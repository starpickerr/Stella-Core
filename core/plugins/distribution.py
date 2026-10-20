"""Core / plugin dual-update coordination with local catalog fetch (D)."""

from __future__ import annotations

import json
import re
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.plugins.package_ops import PackageStore, _iter_package_files, _sha256_tree
from core.plugins.manifest import load_manifest


@dataclass(frozen=True)
class CompatibilityDecision:
    ok: bool
    reason: str
    joint_plan_required: bool = False


def load_default_plugin_manifest(path: Path | None = None) -> dict[str, Any]:
    root = path or Path(__file__).resolve().parents[2] / "resources" / "default-plugins.json"
    return json.loads(root.read_text(encoding="utf-8"))


def check_plugin_api_compatibility(
    *,
    core_api: str,
    package_host_api: str,
    core_supports: str = "1.0.0",
) -> CompatibilityDecision:
    """Check the supported v1 range forms; unknown syntax fails closed."""
    def _parts(version: str) -> tuple[int, int, int]:
        match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+[0-9A-Za-z.-]+)?", version)
        if match is None:
            raise ValueError("unsupported API version")
        return tuple(int(value) for value in match.groups())

    try:
        core = _parts(core_api)
        support = _parts(core_supports)
        pkg_range = package_host_api.strip()
        operator = next((prefix for prefix in (">=", "<=", "^", "~", ">", "<", "=")
                         if pkg_range.startswith(prefix)), "")
        pkg = _parts(pkg_range[len(operator):].strip())
    except (TypeError, ValueError, IndexError):
        return CompatibilityDecision(False, "unparseable Plugin API version")
    if core != support:
        return CompatibilityDecision(False, "core API outside supported version", True)
    if operator == "^":
        upper = ((pkg[0] + 1, 0, 0) if pkg[0] else
                 ((0, pkg[1] + 1, 0) if pkg[1] else (0, 0, pkg[2] + 1)))
        compatible = pkg <= core < upper
    elif operator == "~":
        compatible = pkg <= core < (pkg[0], pkg[1] + 1, 0)
    else:
        compatible = {"": core == pkg, "=": core == pkg, ">=": core >= pkg,
                      "<=": core <= pkg, ">": core > pkg, "<": core < pkg}[operator]
    if not compatible:
        return CompatibilityDecision(False, f"hostApi {pkg_range} excludes {core_api}", True)
    return CompatibilityDecision(True, "compatible")


def plan_bootstrap(offline: bool, staged: list[str] | None = None) -> dict[str, Any]:
    catalog = load_default_plugin_manifest()
    wanted = [row["pluginId"] for row in catalog.get("plugins") or []]
    staged = list(staged or [])
    pending = [plugin_id for plugin_id in wanted if plugin_id not in staged]
    if offline and pending:
        return {
            "status": "blocked_offline",
            "installed": staged,
            "pending": pending,
            "retry": True,
            "pretendInstalled": False,
        }
    return {
        "status": "ready" if not pending else "needs_download",
        "installed": staged,
        "pending": pending,
        "retry": bool(pending),
        "pretendInstalled": False,
    }


def plan_dual_update(
    *,
    core_from: str,
    core_to: str,
    plugin_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Coordinate Core vs plugin updates; never pretend both finished independently.

    Each plugin_updates item: ``{pluginId, fromVersion, toVersion, hostApi}``.
    Incompatible hostApi against ``core_to`` requires a joint plan.
    """
    joint: list[str] = []
    independent: list[str] = []
    blocked: list[dict[str, Any]] = []
    for item in plugin_updates:
        decision = check_plugin_api_compatibility(
            core_api=core_to,
            package_host_api=str(item.get("hostApi") or "^1.0.0"),
            core_supports=core_to,
        )
        plugin_id = str(item.get("pluginId") or "")
        if not decision.ok:
            blocked.append(
                {
                    "pluginId": plugin_id,
                    "reason": decision.reason,
                    "joint_plan_required": decision.joint_plan_required,
                }
            )
            if decision.joint_plan_required:
                joint.append(plugin_id)
        else:
            independent.append(plugin_id)
    core_changing = core_from != core_to
    return {
        "core": {"from": core_from, "to": core_to, "changing": core_changing},
        "independentPlugins": independent,
        "jointPlugins": joint,
        "blocked": blocked,
        "status": "blocked" if blocked and not independent and not core_changing else "planned",
        "applyOrder": (
            ["core", *joint, *independent]
            if core_changing and joint
            else ([*independent] if not core_changing else ["core", *independent])
        ),
    }


def load_catalog(catalog_path: Path) -> dict[str, Any]:
    data = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    if "plugins" not in data:
        raise ValueError("catalog missing plugins")
    return data


def _package_files(root: Path):
    """Source files that participate in package digests (ignore caches/VCS)."""
    yield from _iter_package_files(root)


def verify_package_digest(path: Path, expected_sha256: str) -> bool:
    return _sha256_tree(path) == expected_sha256


def _resolve_catalog_entry_source(catalog_path: Path, entry: dict[str, Any]) -> Path | None:
    """Resolve ``path`` relative to the catalog file (portable; no machine absolutes)."""
    raw = entry.get("path")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = (Path(catalog_path).resolve().parent / path).resolve()
    return path


def fetch_and_install_from_catalog(
    *,
    catalog_path: Path,
    plugin_id: str,
    package_store: PackageStore,
    user_intents: dict[str, str] | None = None,
    prepare_only: bool = False,
) -> dict[str, Any]:
    """Install one catalog entry. Respects disabled/removed user intent."""
    intents = user_intents or {}
    if intents.get(plugin_id) in {"disabled", "removed"}:
        return {"status": "skipped_user_intent", "pluginId": plugin_id, "intent": intents[plugin_id]}
    catalog = load_catalog(catalog_path)
    entry = next((p for p in catalog["plugins"] if p["pluginId"] == plugin_id), None)
    if entry is None:
        raise FileNotFoundError(f"plugin not in catalog: {plugin_id}")
    decision = check_plugin_api_compatibility(
        core_api=catalog.get("coreApi", "1.0.0"),
        package_host_api=entry.get("hostApi", "^1.0.0"),
    )
    if not decision.ok:
        return {"status": "incompatible", "reason": decision.reason, "pluginId": plugin_id}

    catalog_file = Path(catalog_path)
    source = _resolve_catalog_entry_source(catalog_file, entry)
    url = (entry.get("url") or "").strip()
    if url and (source is None or not source.exists()):
        dest = package_store.staging / f"download-{plugin_id}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        archive = dest / "package.bin"
        fetch_url = url
        if "://" not in url:
            # Relative to the catalog file (portable local/release layouts).
            local = (catalog_file.resolve().parent / url).resolve()
            fetch_url = local.as_uri()
        urllib.request.urlretrieve(fetch_url, archive)  # noqa: S310 - catalog trusted URL
        try:
            from core.plugins.signing import unpack_signed_zip

            source = unpack_signed_zip(archive, dest / "unpacked")
        except PermissionError as exc:
            return {"status": "signature_invalid", "pluginId": plugin_id, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - surface as failed install
            return {"status": "failed", "pluginId": plugin_id, "error": str(exc)}

    if source is None or not source.exists():
        return {"status": "missing_source", "pluginId": plugin_id}

    if not verify_package_digest(source, entry["sha256"]):
        return {"status": "digest_mismatch", "pluginId": plugin_id}

    manifest = load_manifest(source)
    if manifest["id"] != plugin_id or (entry.get("version") and manifest["version"] != entry["version"]):
        return {"status": "identity_mismatch", "pluginId": plugin_id}
    decision = check_plugin_api_compatibility(core_api="1.0.0", package_host_api=manifest["hostApi"])
    if not decision.ok:
        return {"status": "incompatible", "reason": decision.reason, "pluginId": plugin_id}

    op = package_store.stage(source)
    op = package_store.inspect(op.operation_id)
    if op.stage.value == "failed":
        return {"status": "failed", "error": op.error, "pluginId": plugin_id}
    op = package_store.prepare(op.operation_id)
    if op.stage.value == "failed":
        return {"status": "failed", "error": op.error, "pluginId": plugin_id}
    if prepare_only:
        return {"status": "prepared", "pluginId": plugin_id, "operationId": op.operation_id,
                "path": op.target_path, "digest": op.digest}
    op = package_store.commit(op.operation_id)
    if op.stage.value == "failed":
        return {"status": "failed", "error": op.error, "pluginId": plugin_id}
    return {
        "status": "installed",
        "pluginId": plugin_id,
        "operationId": op.operation_id,
        "path": op.target_path,
        "digest": op.digest,
    }
