"""Process-wide Plugin Runtime registry for host management surfaces."""

from __future__ import annotations

from core.plugins.registry import PluginRegistry

# Single in-process registry for management UI / HTTP status.
DEFAULT_REGISTRY = PluginRegistry()


def list_published_plugins() -> list[dict]:
    rows = []
    for snap in DEFAULT_REGISTRY.list_snapshots():
        rows.append(
            {
                "pluginId": snap.plugin_id,
                "sourceLabel": snap.source_label,
                "generation": snap.generation,
                "packageDigest": snap.package_digest,
                "services": list(snap.services),
                "contributes": snap.contributes,
            }
        )
    return rows
