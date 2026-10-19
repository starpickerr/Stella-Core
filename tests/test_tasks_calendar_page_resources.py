"""Tasks/Calendar restricted pages must resolve under package ui/pages trees."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.plugins.pages import resolve_page_html


def _package_root(domain: str) -> Path:
    workspace = Path(f"stella-plugins-workspace/plugins/{domain}")
    sibling = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / domain
    if workspace.is_dir() and (workspace / "plugin.json").is_file():
        return workspace.resolve()
    if sibling.is_dir():
        return sibling.resolve()
    pytest.skip(f"{domain} plugin package not present")


@pytest.mark.parametrize("domain,page_id,needle", [
    ("tasks", "tasks.main", "stella.tasks"),
    ("calendar", "calendar.main", "stella.calendar"),
    ("automation", "automation.main", "stella.automation"),
    ("email", "email.main", "stella.email"),
    ("elearning", "elearning.main", "stella.elearning"),
])
def test_domain_main_page_resolves_inside_package(domain, page_id, needle):
    root = _package_root(domain)
    path = resolve_page_html(root, page_id)
    assert path.is_file()
    assert path.name == "index.html"
    assert path.resolve().is_relative_to(root.resolve())
    text = path.read_text(encoding="utf-8")
    assert needle in text
