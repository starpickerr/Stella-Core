from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.plugins.distribution import (
    check_plugin_api_compatibility,
    fetch_and_install_from_catalog,
    load_default_plugin_manifest,
    plan_bootstrap,
    plan_dual_update,
)
from core.plugins.package_ops import PackageStore, _sha256_tree


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


def test_catalog_install_resolves_path_relative_to_catalog(tmp_path):
    sample = Path("samples/plugins/alpha").resolve()
    digest = _sha256_tree(sample)
    pkg_link = tmp_path / "plugins" / "alpha"
    pkg_link.parent.mkdir(parents=True)
    pkg_link.symlink_to(sample)
    catalog_path = tmp_path / "catalog" / "official.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(
        json.dumps(
            {
                "coreApi": "1.0.0",
                "plugins": [
                    {
                        "pluginId": "stella.sample.alpha",
                        "hostApi": "^1.0.0",
                        "path": "../plugins/alpha",
                        "sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = PackageStore(tmp_path / "pkg")
    installed = fetch_and_install_from_catalog(
        catalog_path=catalog_path,
        plugin_id="stella.sample.alpha",
        package_store=store,
    )
    assert installed["status"] == "installed"


def test_catalog_install_respects_removed_intent(tmp_path):
    sample = Path("samples/plugins/alpha")
    digest = _sha256_tree(sample)
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


def test_dual_update_blocks_incompatible_plugin_without_pretending_success():
    plan = plan_dual_update(
        core_from="1.0.0",
        core_to="1.1.0",
        plugin_updates=[
            {"pluginId": "stella.bills", "fromVersion": "1.0.0", "toVersion": "1.1.0", "hostApi": "^1.0.0"},
            {"pluginId": "stella.tasks", "fromVersion": "1.0.0", "toVersion": "2.0.0", "hostApi": "^2.0.0"},
        ],
    )
    assert "stella.bills" in plan["independentPlugins"]
    assert "stella.tasks" in plan["jointPlugins"]
    assert plan["blocked"]
    assert plan["core"]["changing"] is True


@pytest.mark.parametrize("core,required,compatible", [
    ("1.0.0", "^1.1.0", False),
    ("1.0.0", "~1.0.1", False),
    ("1.1.0", "1.0.0", False),
    ("1.1.0", "^1.0.0", True),
    ("0.3.0", "^0.2.0", False),
    ("1.0.0", "garbage", False),
    ("1.0.0", ">=2.0.0", False),
])
def test_host_api_range_is_enforced(core, required, compatible):
    assert check_plugin_api_compatibility(
        core_api=core, package_host_api=required, core_supports=core,
    ).ok is compatible


def test_catalog_identity_must_match_package(tmp_path):
    sample = Path("samples/plugins/alpha").resolve()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"coreApi": "1.0.0", "plugins": [{
        "pluginId": "stella.bills", "path": str(sample), "sha256": _sha256_tree(sample),
        "version": "1.0.0", "hostApi": "^1.0.0",
    }]}))
    store = PackageStore(tmp_path / "pkg")
    result = fetch_and_install_from_catalog(catalog_path=catalog, plugin_id="stella.bills", package_store=store)
    assert result["status"] == "identity_mismatch"
    assert store.current_package("stella.sample.alpha") is None
