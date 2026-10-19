"""Bills plugin page assets must resolve under the package ui/pages tree."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.pages import resolve_page_html


WORKSPACE = Path("stella-plugins-workspace/plugins/bills")
SIBLING = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "bills"


def _package_root() -> Path:
    if WORKSPACE.is_dir():
        return WORKSPACE.resolve()
    if SIBLING.is_dir():
        return SIBLING.resolve()
    pytest.skip("bills plugin package not present")


def test_bills_main_page_resolves_inside_package():
    root = _package_root()
    path = resolve_page_html(root, "bills.main")
    assert path.is_file()
    assert path.name == "index.html"
    assert path.resolve().is_relative_to(root.resolve())
    text = path.read_text(encoding="utf-8")
    assert "stella.bills" in text or "bills" in text.lower()


def test_page_id_rejects_path_escape(tmp_path):
    root = tmp_path / "pkg"
    (root / "ui" / "pages" / "safe").mkdir(parents=True)
    (root / "ui" / "pages" / "safe" / "index.html").write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_page_html(root, "../secret")
    with pytest.raises(ValueError):
        resolve_page_html(root, "safe/../../secret")
    with pytest.raises(FileNotFoundError):
        resolve_page_html(root, "missing.page")
