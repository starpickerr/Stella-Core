"""Briefing restricted page must resolve under package ui/pages tree."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.pages import resolve_page_html


def _package_root() -> Path:
    workspace = Path("stella-plugins-workspace/plugins/briefing")
    sibling = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "briefing"
    if workspace.is_dir() and (workspace / "plugin.json").is_file():
        return workspace.resolve()
    if sibling.is_dir():
        return sibling.resolve()
    pytest.skip("briefing plugin package not present")


def test_briefing_main_page_resolves_inside_package():
    root = _package_root()
    path = resolve_page_html(root, "briefing.main")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "stella.briefing" in text
