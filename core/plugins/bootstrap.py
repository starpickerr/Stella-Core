"""First-boot / desktop default plugin install and process-env activation (D / G5)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.plugins.distribution import fetch_and_install_from_catalog, load_default_plugin_manifest
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
        result = fetch_and_install_from_catalog(
            catalog_path=catalog_path,
            plugin_id=plugin_id,
            package_store=package_store,
            user_intents=intents,
        )
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
    store = PackageStore(Path(data_dir) / "plugin-packages")
    intents_path = Path(data_dir) / "plugin-intents.json"
    intents = {}
    if intents_path.is_file():
        intents = json.loads(intents_path.read_text(encoding="utf-8"))
    catalog = catalog_path or _default_catalog_path()
    result = bootstrap_default_plugins(
        catalog_path=catalog,
        package_store=store,
        user_intents=intents,
    )
    intents_path.parent.mkdir(parents=True, exist_ok=True)
    intents_path.write_text(json.dumps(result.get("intents") or intents, indent=2) + "\n", encoding="utf-8")
    installed = list(result.get("installed") or [])
    # Also activate already-committed packages from prior boots.
    for plugin_id in DOMAIN_ENV:
        if store.current_package(plugin_id) and plugin_id not in installed:
            if intents.get(plugin_id) not in {"disabled", "removed"}:
                installed.append(plugin_id)
    applied = apply_desktop_plugin_defaults(installed_ids=installed, intents_path=intents_path)
    result["envApplied"] = applied
    return result


def _default_catalog_path() -> Path:
    sibling = Path(__file__).resolve().parents[3] / "Stella-Plugins" / "catalog" / "official.json"
    # Workspace mirrors packages but has no catalog file; callers may synthesize.
    return sibling
