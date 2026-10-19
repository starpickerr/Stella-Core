"""Frozen backend must ship resources/default-plugins.json (first-boot bootstrap / R10)."""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "desktop" / "build" / "stella-backend.spec"
MANIFEST = REPO / "resources" / "default-plugins.json"


def test_default_plugins_manifest_exists():
    assert MANIFEST.is_file()
    data = MANIFEST.read_text(encoding="utf-8")
    assert "stella.bills" in data


def test_backend_spec_ships_default_plugins_json():
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    joined: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "rp":
            parts = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if parts:
                joined.append("/".join(parts))
    assert "resources/default-plugins.json" in joined, (
        "stella-backend.spec must include resources/default-plugins.json in datas"
    )
