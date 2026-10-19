from __future__ import annotations

from pathlib import Path

from core.plugins.package_ops import PackageStage, PackageStore


def test_stage_inspect_prepare_commit(tmp_path):
    store = PackageStore(tmp_path / "pkg")
    op = store.stage(Path("samples/plugins/alpha"))
    assert op.stage == PackageStage.STAGED
    op = store.inspect(op.operation_id)
    assert op.stage == PackageStage.VERIFIED
    op = store.prepare(op.operation_id)
    assert op.stage == PackageStage.PREPARED
    assert Path(op.target_path).joinpath("plugin.json").is_file()
    op = store.commit(op.operation_id)
    assert op.stage == PackageStage.COMMITTED
    current = store.current_package("stella.sample.alpha")
    assert current is not None
    assert current["digest"] == op.digest
    assert store.get_operation(op.operation_id).stage == PackageStage.COMMITTED
