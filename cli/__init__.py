"""Stella CLI - Manage your Stella from the command line."""

from pathlib import Path


def _read_version() -> str:
    """Product version. Source checkout reads the repo-root VERSION file;
    an installed wheel falls back to the package metadata written from the
    same file at build time."""
    root_file = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        text = root_file.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    try:
        from importlib.metadata import version

        return version("stella")
    except Exception:
        return "0.0.0"


__version__ = _read_version()
