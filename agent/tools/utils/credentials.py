"""
Shared credential-path guard for file tools.

The agent's API keys live in ~/.stella/.env and must only ever be reached through
the env_config tool. Every tool that can surface file contents to the model has
to apply the same check - guarding only the read tool leaves the others as
bypasses (a successful edit, for example, returns a diff containing the
surrounding lines).

Scope is deliberately narrow (the credential file and its process-environment
aliases) so this does not re-broaden the block that issue #2863 intentionally
narrowed to ~/.stella/.env. See also issue #2913 for the bypasses handled here.
"""

from __future__ import annotations

import os
import re

from common.utils import expand_path

# Paths whose CONTENT mirrors the process environment (and thus any secrets
# loaded from ~/.stella/.env). Reading them bypasses the env_config boundary.
# Matches /proc/self/environ, /proc/thread-self/environ and /proc/<pid>/environ.
_PROC_ENVIRON_RE = re.compile(r"^/proc/(\d+|self|thread-self)/environ$")

DENIED_MESSAGE = (
    "Error: Access denied. API keys and credentials must be accessed "
    "through the env_config tool only."
)


def protected_credential_paths() -> set[str]:
    from config import get_data_root, get_weixin_credentials_path
    from common.state_dir import mcp_config_file, shared_root
    return {os.path.realpath(path) for path in (
        expand_path("~/.stella/.env"),
        os.path.join(get_data_root(), "config.json"),
        get_weixin_credentials_path(),
        str(mcp_config_file()),
        str(shared_root() / ".env"),
    )}


def is_credential_path(absolute_path: str, protected_paths: set[str] | None = None) -> bool:
    """Return True if *absolute_path* points at protected credential data.

    Beyond the literal ~/.stella/.env file, this also blocks two real bypass
    surfaces reported in issue #2913:
      1. /proc/<pid|self|thread-self>/environ - a second view of the
         process environment that leaks secrets loaded from ~/.stella/.env.
      2. Symlinks resolving to ~/.stella/.env; an exact abspath match keeps the
         link target and can be bypassed.
    """
    # Compare on both the normalized path and the symlink-resolved path,
    # in POSIX form so the /proc regex matches regardless of os.sep.
    candidates = set()
    try:
        candidates.add(os.path.normpath(absolute_path).replace(os.sep, "/"))
        candidates.add(os.path.realpath(absolute_path).replace(os.sep, "/"))
    except OSError:
        candidates.add(absolute_path.replace(os.sep, "/"))

    # 1. /proc environ aliases (checked on raw and symlink-resolved forms).
    for candidate in candidates:
        if _PROC_ENVIRON_RE.match(candidate):
            return True

    # 2. The credential file itself, following symlinks on both sides.
    return any(path.replace(os.sep, "/") in candidates for path in (protected_paths or protected_credential_paths()))
