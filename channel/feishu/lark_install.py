"""
On-demand installer for the ``lark_oapi`` SDK (Feishu channel).

Why this exists
---------------
The desktop client (PyInstaller build) intentionally does **not** bundle
``lark_oapi`` (~116MB + dependencies) so the base download stays small
(see zhayujie/CowAgent#2987 — "客户端没有飞书通道"). Instead, the first time a
user enables the Feishu channel in desktop mode, we pip-install ``lark_oapi``
(and its dependencies) into a writable per-user directory and add it to
``sys.path``. The module is then imported lazily as before.

For source / non-desktop installs ``lark_oapi`` is expected to be present
already (it lives in ``requirements.txt``); in that case this module is a
no-op that simply imports it.
"""
import importlib.util
import logging
import os
import subprocess
import sys

try:
    from common.log import logger
except Exception:  # pragma: no cover - common may be unavailable in isolation
    logger = logging.getLogger("feishu_lark_install")

LARK_PKG = "lark-oapi"
LARK_MIN = "1.5.5"

# Per-user, writable, persistent location. Mirrors the browser tool's ~/.cow
# layout so everything CowAgent owns lives under one roof.
_VENDOR_SUBDIR = os.path.join(".cow", "feishu_vendor")


def vendor_dir() -> str:
    """Return (and create) the directory where lark_oapi is installed on demand."""
    base = os.environ.get("COW_DATA_DIR") or os.path.expanduser("~")
    path = os.path.join(base, _VENDOR_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def is_available() -> bool:
    """True if lark_oapi can already be imported."""
    return importlib.util.find_spec("lark_oapi") is not None


def ensure(allow_install: bool = True) -> None:
    """Ensure ``lark_oapi`` can be imported.

    - If already importable, return immediately (source installs, or a previous
      on-demand install that persisted).
    - In desktop mode (``COW_DESKTOP=1``) and when ``allow_install`` is True,
      pip-install ``lark_oapi`` (and its dependencies) on demand into
      :func:`vendor_dir` and add that directory to ``sys.path``.
    - Otherwise (non-desktop without the package, or install disabled) raise
      ``ImportError`` with actionable guidance.
    """
    # Fast path: already importable.
    if is_available():
        return

    if not allow_install:
        raise ImportError(
            "lark_oapi is required for the Feishu channel but is not installed. "
            "Install it with: pip install -U 'lark-oapi>=%s'" % LARK_MIN
        )

    # Source / non-desktop installs should already have it via requirements.txt.
    if os.environ.get("COW_DESKTOP") != "1":
        raise ImportError(
            "lark_oapi is required for the Feishu channel but is not installed. "
            "Install it with: pip install -U 'lark-oapi>=%s'" % LARK_MIN
        )

    # Desktop mode: install on demand into the user-writable vendor dir.
    vdir = vendor_dir()
    if vdir not in sys.path:
        sys.path.insert(0, vdir)
    # Re-check: a previous run may have already installed it here.
    if is_available():
        return

    logger.warning(
        "[FeiShu] lark_oapi not found; installing on demand into %s "
        "(requires network, ~%s+). This only happens once.",
        vdir, LARK_MIN,
    )
    try:
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                "--target", vdir,
                "--upgrade",
                "lark-oapi>=%s" % LARK_MIN,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:  # noqa: BLE001 - surface a clear, actionable error
        logger.error("[FeiShu] on-demand lark_oapi install failed: %s", exc)
        raise ImportError(
            "Failed to install lark_oapi on demand. A network connection is "
            "required the first time you enable Feishu. Please connect to the "
            "internet and retry, or install it manually with: "
            "pip install -U 'lark-oapi>=%s'" % LARK_MIN
        ) from exc

    if not is_available():
        raise ImportError(
            "lark_oapi could not be imported after on-demand installation. "
            "Try installing manually: pip install -U 'lark-oapi>=%s'" % LARK_MIN
        )
    logger.info("[FeiShu] lark_oapi installed on demand into %s", vdir)
