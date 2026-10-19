"""Package digests and signed ZIPs must ignore local test caches."""

from __future__ import annotations

from pathlib import Path

from core.plugins.distribution import _package_files
from core.plugins.signing import write_signed_zip
import zipfile


def test_package_files_skips_pytest_cache_and_git(tmp_path):
    root = tmp_path / "pkg"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "main.py").write_text("ok\n", encoding="utf-8")
    cache = root / ".pytest_cache" / "v" / "cache"
    cache.mkdir(parents=True)
    (cache / "nodeids").write_text("x\n", encoding="utf-8")
    git = root / ".git" / "objects"
    git.mkdir(parents=True)
    (git / "deadbeef").write_text("blob\n", encoding="utf-8")
    names = {path.relative_to(root).as_posix() for path in _package_files(root)}
    assert names == {"backend/main.py"}


def test_signed_zip_omits_pytest_cache(tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "plugin.json").write_text('{"id":"x"}', encoding="utf-8")
    cache = root / ".pytest_cache"
    cache.mkdir()
    (cache / "README.md").write_text("cache\n", encoding="utf-8")
    archive = tmp_path / "pkg.zip"
    write_signed_zip(root, archive, secret=b"test-secret")
    with zipfile.ZipFile(archive) as outer:
        inner = tmp_path / "inner.zip"
        inner.write_bytes(outer.read("package.zip"))
    with zipfile.ZipFile(inner) as zf:
        names = set(zf.namelist())
    assert "plugin.json" in names
    assert not any(name.startswith(".pytest_cache") for name in names)
