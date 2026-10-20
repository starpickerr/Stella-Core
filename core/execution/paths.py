"""Constrain host-created task paths before any directories are written."""
import re
from pathlib import Path


def managed_child(root: Path, *identifiers: str) -> Path:
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) for value in identifiers):
        raise ValueError("execution and attempt identifiers must be safe path segments")
    root = Path(root).resolve()
    destination = root.joinpath(*identifiers).resolve()
    if not destination.is_relative_to(root):
        raise PermissionError("path escapes managed execution root")
    return destination
