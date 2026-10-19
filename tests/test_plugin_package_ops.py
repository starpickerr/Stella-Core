from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "stop_after,resume",
    [
        (PackageStage.STAGED, ("inspect", "prepare", "commit")),
        (PackageStage.VERIFIED, ("prepare", "commit")),
        (PackageStage.PREPARED, ("commit",)),
    ],
)
def test_r07_resume_after_each_durable_stage(tmp_path, stop_after, resume):
    """Recreate the store from disk after each persistent stage (R07)."""
    root = tmp_path / "pkg"
    store = PackageStore(root)
    op = store.stage(Path("samples/plugins/alpha"))
    if stop_after in {PackageStage.VERIFIED, PackageStage.PREPARED}:
        op = store.inspect(op.operation_id)
    if stop_after == PackageStage.PREPARED:
        op = store.prepare(op.operation_id)
    assert store.get_operation(op.operation_id).stage == stop_after

    # Simulate process death: new PackageStore instance, same on-disk root.
    store2 = PackageStore(root)
    op2 = store2.get_operation(op.operation_id)
    assert op2.stage == stop_after
    for step in resume:
        op2 = getattr(store2, step)(op.operation_id)
    assert op2.stage == PackageStage.COMMITTED
    current = store2.current_package("stella.sample.alpha")
    assert current is not None
    assert current["digest"] == op2.digest
