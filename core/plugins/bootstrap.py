"""First-boot / desktop default plugin install and process-env activation (D / G5)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from core.plugins.distribution import fetch_and_install_from_catalog, load_default_plugin_manifest, verify_package_digest
from core.plugins.manifest import load_manifest
from core.plugins.package_ops import PackageStore

DOMAIN_ENV = {
    "stella.bills": "STELLA_BILLS_PLUGIN",
    "stella.calendar": "STELLA_CALENDAR_PLUGIN",
    "stella.tasks": "STELLA_TODOS_PLUGIN",
    "stella.email": "STELLA_EMAIL_PLUGIN",
    "stella.elearning": "STELLA_ELEARNING_PLUGIN",
    "stella.briefing": "STELLA_BRIEFING_PLUGIN",
    "stella.automation": "STELLA_AUTOMATION_PLUGIN",
}


def bootstrap_default_plugins(
    *,
    catalog_path: Path,
    package_store: PackageStore,
    plugin_ids: list[str] | None = None,
    user_intents: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Install listed (or default-manifest) plugins. Never resurrects removed/disabled."""
    wanted = list(plugin_ids or [])
    if not wanted:
        wanted = [row["pluginId"] for row in load_default_plugin_manifest().get("plugins") or []]
    intents = dict(user_intents or {})
    installed: list[str] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for plugin_id in wanted:
        try:
            if intents.get(plugin_id) in {"disabled", "removed"}:
                result = {"status": "skipped_user_intent", "pluginId": plugin_id, "intent": intents[plugin_id]}
            elif current := package_store.current_package(plugin_id):
                # Bootstrap fills missing defaults; updates are an explicit operation.
                # Keep the exact installed version even when the catalog is offline.
                root = Path(current["path"])
                if not root.is_dir() or not verify_package_digest(root, current["digest"]):
                    raise ValueError("installed package is missing or corrupt; repair required")
                manifest = load_manifest(root)
                if manifest["id"] != plugin_id or manifest["version"] != current["version"]:
                    raise ValueError("installed package identity mismatch")
                result = {"status": "installed", "pluginId": plugin_id}
            else:
                result = fetch_and_install_from_catalog(
                    catalog_path=catalog_path,
                    plugin_id=plugin_id,
                    package_store=package_store,
                    user_intents=intents,
                )
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            result = {"status": "failed", "pluginId": plugin_id, "error": str(exc)}
        status = result.get("status")
        if status == "installed":
            installed.append(plugin_id)
            intents.setdefault(plugin_id, "enabled")
        elif status == "skipped_user_intent":
            skipped.append(result)
        else:
            failed.append(result)
    return {
        "status": "ok" if not failed else "partial",
        "installed": installed,
        "skipped": skipped,
        "failed": failed,
        "intents": intents,
    }


def apply_desktop_plugin_defaults(
    *,
    installed_ids: list[str],
    intents_path: Path | None = None,
) -> dict[str, str]:
    """On STELLA_DESKTOP, set domain env flags for installed+enabled plugins.

    Explicit ``0``/``false``/``no`` always wins. Missing env is filled with ``1``.
    """
    if os.environ.get("STELLA_DESKTOP", "").strip().lower() not in {"1", "true", "yes"}:
        return {}
    intents: dict[str, str] = {}
    if intents_path and intents_path.is_file():
        intents = json.loads(intents_path.read_text(encoding="utf-8"))
    applied: dict[str, str] = {}
    for plugin_id in installed_ids:
        env_name = DOMAIN_ENV.get(plugin_id)
        if not env_name:
            continue
        if intents.get(plugin_id) in {"disabled", "removed"}:
            continue
        current = os.environ.get(env_name, "").strip().lower()
        if current in {"0", "false", "no"}:
            continue
        if current in {"1", "true", "yes"}:
            applied[env_name] = current
            continue
        os.environ[env_name] = "1"
        applied[env_name] = "1"
    return applied


def run_desktop_bootstrap(
    *,
    data_dir: Path,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Install default catalog into the user package store and activate env flags."""
    from core.plugins.lifecycle import PluginManager
    from core.plugins.management import ManagementStore
    from core.plugins.package_ops import _atomic_json

    management = ManagementStore(Path(data_dir) / "plugin-packages")
    manager = PluginManager(management, catalog_path=catalog_path or _default_catalog_path())
    intents_path = Path(data_dir) / "plugin-intents.json"
    legacy_intents = json.loads(intents_path.read_text()) if intents_path.is_file() else {}
    installed, skipped, failed = [], [], []
    user = "local-default"
    wanted = [row['pluginId'] for row in load_default_plugin_manifest()['plugins']]
    for plugin_id in wanted:
        if not management.has_instance(plugin_id, user):
            intent = legacy_intents.get(plugin_id, 'enabled')
            explicit = os.environ.get(DOMAIN_ENV.get(plugin_id, ''), '').strip().lower()
            if explicit in {'0', 'false', 'no'}:
                intent = 'disabled'
            management.set_intent(plugin_id, user, intent)
        current = management.instance(plugin_id, user)
        if current['intent'] in {'disabled', 'removed'}:
            skipped.append({'pluginId': plugin_id, 'status': 'skipped_user_intent', 'intent': current['intent']})
            continue
        try:
            pending = [op for op in management.unfinished(plugin_id) if op['kind'] == 'install']
            if pending:
                manager.resume(pending[0]['operationId'])
            elif manager.packages.current_package(plugin_id):
                # Validate installed bytes offline. Migration markers make this
                # adoption idempotent; no catalog fetch or version replacement.
                manager.adopt_current(plugin_id, user_id=user)
            else:
                manager.install(plugin_id, user_id=user)
            installed.append(plugin_id)
        except Exception as exc:
            management.set_runtime(plugin_id, user, 'maintenance', error=str(exc))
            failed.append({'pluginId': plugin_id, 'status': 'failed', 'error': str(exc)})
    intents = {plugin_id: management.instance(plugin_id, user)['intent'] for plugin_id in wanted}
    intents_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(intents_path, intents)
    applied = apply_desktop_plugin_defaults(installed_ids=installed, intents_path=intents_path)
    return {'status': 'ok' if not failed else 'partial', 'installed': installed,
            'skipped': skipped, 'failed': failed, 'intents': intents, 'envApplied': applied}


def _default_catalog_path() -> Path:
    """Resolve the official catalog for bootstrap.

    Order: ``STELLA_PLUGIN_CATALOG`` → Electron Resources seed → frozen
    ``_MEIPASS`` copy → sibling Stella-Plugins checkout.
    """
    explicit = os.environ.get("STELLA_PLUGIN_CATALOG", "").strip()
    if explicit:
        return Path(explicit)
    # Packaged app: <Resources>/backend/stella-backend/stella-backend → ../../plugin-catalog.json
    if getattr(sys, "frozen", False):
        resources_catalog = Path(sys.executable).resolve().parents[2] / "plugin-catalog.json"
        if resources_catalog.is_file():
            return resources_catalog
    here = Path(__file__).resolve()
    meipass = Path(getattr(sys, "_MEIPASS", here.parents[2]))
    bundled = meipass / "resources" / "plugin-catalog.json"
    if bundled.is_file():
        return bundled
    sibling = here.parents[3] / "Stella-Plugins" / "catalog" / "official.json"
    return sibling
