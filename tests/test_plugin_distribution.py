from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.plugins.distribution import (
    check_plugin_api_compatibility,
    fetch_and_install_from_catalog,
    load_default_plugin_manifest,
    plan_bootstrap,
)
from core.plugins.package_ops import PackageStore


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def test_default_plugins_list_includes_bills():
    data = load_default_plugin_manifest()
    ids = {row["pluginId"] for row in data["plugins"]}
    assert "stella.bills" in ids


def test_api_caret_incompatible_requires_joint_plan():
    decision = check_plugin_api_compatibility(core_api="1.0.0", package_host_api="^2.0.0")
    assert decision.ok is False
    assert decision.joint_plan_required is True


def test_offline_bootstrap_does_not_pretend_installed():
    plan = plan_bootstrap(offline=True, staged=[])
    assert plan["status"] == "blocked_offline"
    assert plan["pretendInstalled"] is False


def test_catalog_install_respects_removed_intent(tmp_path):
    sample = Path("samples/plugins/alpha")
    digest = _tree_digest(sample)
    catalog = {
        "coreApi": "1.0.0",
        "plugins": [
            {
                "pluginId": "stella.sample.alpha",
                "hostApi": "^1.0.0",
                "path": str(sample.resolve()),
                "sha256": digest,
            }
        ],
    }
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    store = PackageStore(tmp_path / "pkg")
    skipped = fetch_and_install_from_catalog(
        catalog_path=catalog_path,
        plugin_id="stella.sample.alpha",
        package_store=store,
        user_intents={"stella.sample.alpha": "removed"},
    )
    assert skipped["status"] == "skipped_user_intent"
    installed = fetch_and_install_from_catalog(
        catalog_path=catalog_path,
        plugin_id="stella.sample.alpha",
        package_store=store,
    )
    assert installed["status"] == "installed"
    # Re-prepare same digest must not fail (immutable cache)
    again = fetch_and_install_from_catalog(
        catalog_path=catalog_path,
        plugin_id="stella.sample.alpha",
        package_store=store,
    )
    assert again["status"] == "installed"
