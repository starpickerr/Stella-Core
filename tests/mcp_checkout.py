"""Skip Core tests that need a sibling MCP checkout when that checkout is absent."""

from pathlib import Path

import pytest


def require_checkout(path: Path, reason: str) -> Path:
    """Stop collection when an external MCP file is not in this checkout."""
    if not path.is_file():
        pytest.skip(reason, allow_module_level=True)
    return path
