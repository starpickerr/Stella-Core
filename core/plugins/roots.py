"""Resolve on-disk roots for first-party plugin packages (dev checkout vs installed store)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    # core/plugins/roots.py -> Stella-Core
    return Path(__file__).resolve().parents[2]


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"))


def resolve_plugin_package_root(
    *,
    plugin_id: str,
    env_var: str,
    folder_name: str,
) -> Path:
    """Managed packages use the shared, verified selection without overrides.

    Explicit source roots remain a development compatibility path only before
    a user is enrolled in managed package execution.
    """
    from common.state_dir import shared_root
    from core.plugins.caller import plugin_user_id, managed_plugin
    from core.plugins.management import default_store
    from core.plugins.package_ops import PackageStore, _sha256_tree

    managed = managed_plugin(plugin_id, plugin_user_id())
    explicit = os.environ.get(env_var, "").strip()
    if explicit and not managed:
        return Path(explicit)
    root = default_store().root if managed else shared_root() / "plugin-packages"
    current = PackageStore(root).current_package(plugin_id)
    if current:
        installed = Path(current.get("path") or "")
        if not installed.is_dir() or _sha256_tree(installed) != current.get("digest"):
            raise PermissionError(f"installed plugin package missing or corrupt: {plugin_id}")
        return installed
    if managed:
        raise FileNotFoundError(f"installed package selection missing: {plugin_id}")

    sibling = _repo_root().parent / "Stella-Plugins" / "plugins" / folder_name
    if sibling.is_dir():
        return sibling

    workspace = _repo_root() / "stella-plugins-workspace" / "plugins" / folder_name
    if workspace.is_dir() and not _is_frozen():
        return workspace

    raise FileNotFoundError(
        f"plugin package not found for {plugin_id}: set {env_var} or install via catalog"
    )
