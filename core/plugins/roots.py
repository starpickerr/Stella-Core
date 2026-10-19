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
    """Locate a domain package for PluginSession.

    Order: explicit env → committed PackageStore under state_root → sibling
    ``Stella-Plugins/plugins/<folder>`` → (source tree only) workspace mirror.
    """
    explicit = os.environ.get(env_var, "").strip()
    if explicit:
        return Path(explicit)

    try:
        from common.state_dir import state_root
        from core.plugins.package_ops import PackageStore

        current = PackageStore(state_root() / "plugin-packages").current_package(plugin_id)
        if current and current.get("path"):
            installed = Path(current["path"])
            if installed.is_dir():
                return installed
    except Exception:
        pass

    sibling = _repo_root().parent / "Stella-Plugins" / "plugins" / folder_name
    if sibling.is_dir():
        return sibling

    workspace = _repo_root() / "stella-plugins-workspace" / "plugins" / folder_name
    if workspace.is_dir() and not _is_frozen():
        return workspace

    raise FileNotFoundError(
        f"plugin package not found for {plugin_id}: set {env_var} or install via catalog"
    )
