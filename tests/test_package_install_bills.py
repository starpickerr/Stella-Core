"""P2d: install Bills workspace package via local package transaction."""

from __future__ import annotations

from pathlib import Path

from core.plugins.host import PluginSession
from core.plugins.package_ops import PackageStage, PackageStore
from core.plugins.runtime_hub import DEFAULT_REGISTRY


def test_commit_bills_package_and_ping_service(tmp_path):
    store = PackageStore(tmp_path / "pkg")
    op = store.stage(Path("stella-plugins-workspace/plugins/bills"))
    op = store.inspect(op.operation_id)
    op = store.prepare(op.operation_id)
    op = store.commit(op.operation_id)
    assert op.stage == PackageStage.COMMITTED
    current = store.current_package("stella.bills")
    assert current is not None
    session = PluginSession(
        Path(current["path"]),
        source_label="local-cache",
        registry=DEFAULT_REGISTRY,
    )
    try:
        started = session.start()
        assert started["initialize"]["pluginId"] == "stella.bills"
        listed = session.invoke(
            "list_ledger",
            {"year": 2026, "month": 1, "_dataHandle": {"dbPath": str(tmp_path / "bills.db")}},
        )
        assert listed["status"] == "succeeded"
    finally:
        session.dispose()
