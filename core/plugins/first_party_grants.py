"""Issue scoped grants for required first-party capabilities when a user enables a plugin.

Managed packages never receive silent compatibility grants on worker start.
Desktop first-boot / explicit enable therefore records the equivalent of the
user approving each ``permissions[].required`` capability for self-consumption.
"""

from __future__ import annotations

from pathlib import Path

from core.plugins.authz import DEFAULT_AUTHZ, PluginAuthorizationStore
from core.plugins.caller import user_grant_ref
from core.plugins.host import PluginSession
from core.plugins.manifest import load_manifest
from core.plugins.package_ops import PackageStore
from core.plugins.registry import PluginRegistry


def issue_required_grants_for_enabled_plugin(
    *,
    plugin_id: str,
    user_id: str,
    package_root: Path | None = None,
    authz: PluginAuthorizationStore | None = None,
) -> list[str]:
    """Create interactive + background scoped grants for required capabilities.

    Returns grant refs that were created or already present. Idempotent.
    """
    store = authz or DEFAULT_AUTHZ
    root = Path(package_root) if package_root else _current_root(plugin_id)
    manifest = load_manifest(root)
    required = [
        row["capability"]
        for row in (manifest.get("permissions") or [])
        if row.get("required") and row.get("capability")
    ]
    if not required:
        return []
    methods_by_capability = _methods_by_capability(root, user_id)
    domain = plugin_id.removeprefix("stella.")
    parent = user_grant_ref(f"{domain}-default-grant", user_id)
    issued: list[str] = []
    resource = {"kind": "user", "id": user_id}
    for capability in required:
        methods = methods_by_capability.get(capability) or []
        if not methods:
            continue
        for purpose in ("interactive", "background"):
            grant_ref = f"{parent}:{purpose}:{capability}"
            store.issue_scoped(
                grant_ref=grant_ref,
                parent_ref=parent,
                plugin_id=plugin_id,
                user_id=user_id,
                consumer_plugin_id=plugin_id,
                capability=capability,
                methods=methods,
                resources=[resource],
                purpose=purpose,
            )
            issued.append(grant_ref)
    return issued


def _current_root(plugin_id: str) -> Path:
    from core.plugins.management import default_store

    current = PackageStore(default_store().root).current_package(plugin_id)
    if not current:
        raise FileNotFoundError(f"installed package missing: {plugin_id}")
    return Path(current["path"])


def _methods_by_capability(root: Path, user_id: str) -> dict[str, list[str]]:
    session = PluginSession(
        root, source_label="first-party-grants", registry=PluginRegistry(),
        user_id=user_id, maintenance=True,
    )
    try:
        prepared = session.start()["prepare"]
        mapping: dict[str, list[str]] = {}
        for service in prepared.get("services") or []:
            for method in service.get("methods") or []:
                name = method.get("name")
                for capability in method.get("permissions") or []:
                    mapping.setdefault(capability, []).append(name)
        return {key: sorted(set(values)) for key, values in mapping.items()}
    finally:
        session.dispose()
