"""Resolve restricted plugin page HTML under package ui/pages/{id}/index.html."""

from __future__ import annotations

import re
from pathlib import Path

_PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def resolve_page_html(package_root: Path, page_id: str) -> Path:
    """Return the page index.html; reject escapes and missing pages."""
    if not isinstance(page_id, str) or not _PAGE_ID.fullmatch(page_id):
        raise ValueError(f"invalid page id: {page_id!r}")
    root = Path(package_root).resolve()
    target = (root / "ui" / "pages" / page_id / "index.html").resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"page escapes package root: {page_id!r}") from exc
    if not target.is_file():
        raise FileNotFoundError(f"plugin page not found: {page_id}")
    return target
