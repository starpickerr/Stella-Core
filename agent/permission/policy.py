"""Read existing permission values and migrate them to Security Center presets.

This module does not authorize tool calls. All execution decisions live in
:mod:`agent.permission.gateway`.
"""

from __future__ import annotations

from typing import Any, Optional

READ_ONLY = "read-only"
WORKSPACE_WRITE = "workspace-write"
FULL_ACCESS = "full-access"
MODES = (READ_ONLY, WORKSPACE_WRITE, FULL_ACCESS)
DEFAULT_MODE = WORKSPACE_WRITE
CONFIG_KEY = "agent_permission_mode"
_ALIASES = {
    "readonly": READ_ONLY, "read_only": READ_ONLY, "ro": READ_ONLY,
    "workspace": WORKSPACE_WRITE, "workspace_write": WORKSPACE_WRITE,
    "workspacewrite": WORKSPACE_WRITE, "write": WORKSPACE_WRITE,
    "full": FULL_ACCESS, "full_access": FULL_ACCESS, "fullaccess": FULL_ACCESS,
    "danger-full-access": FULL_ACCESS, "all": FULL_ACCESS,
}


def normalize_mode(value: Any, default: Optional[str] = None) -> str:
    fallback = default if default in MODES else DEFAULT_MODE
    if not isinstance(value, str):
        return fallback if value is None else READ_ONLY
    value = value.strip().lower()
    if not value:
        return fallback
    return value if value in MODES else _ALIASES.get(value, READ_ONLY)


def global_mode() -> str:
    try:
        from config import conf
        return normalize_mode(conf().get(CONFIG_KEY))
    except Exception:
        return DEFAULT_MODE
