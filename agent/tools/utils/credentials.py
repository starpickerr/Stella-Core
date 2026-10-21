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
ELEARNING_DENIED_MESSAGE = (
    "Error: Direct access to eLearning login settings and session cookies is denied; "
    "workspace_outside permission does not grant credential access. Use the "
    "eLearning MCP for courses, fetch, or sync_files; it uses the saved session "
    "internally. If login times out, retry login in eLearning settings."
)


def is_elearning_credential_path(absolute_path: str) -> bool:
    from common.state_dir import briefing_db
    base = briefing_db(ensure=False)
    config = os.path.realpath(base.with_name('elearning.json'))
    roots = (os.path.realpath(base.parent / 'elearning-sessions'),
             os.path.realpath(base.parent.parent / 'elearning'))
    candidates = (os.path.normpath(absolute_path), os.path.realpath(absolute_path))
    return any(path == config or any(path == root or path.startswith(root + os.sep) for root in roots)
               for path in candidates)


def credential_denial_message(absolute_path: str) -> str:
    from common.state_dir import data_service_db
    root=os.path.realpath(data_service_db(ensure=False).parent)
    real=os.path.realpath(absolute_path)
    if real==root or real.startswith(root+os.sep):
        return 'Managed data must be accessed through Data Service or Data Management; raw file access is denied.'
    return ELEARNING_DENIED_MESSAGE if is_elearning_credential_path(absolute_path) else DENIED_MESSAGE


def protected_credential_paths() -> set[str]:
    from config import get_data_root, get_weixin_credentials_path
    from common.state_dir import mcp_config_file, shared_root, state_root, briefing_db
    email_db = briefing_db(ensure=False).parent.parent / "email/email.db"
    elearning_config = briefing_db(ensure=False).with_name('elearning.json')
    return {os.path.realpath(path) for path in (
        expand_path("~/.stella/.env"),
        os.path.join(get_data_root(), "config.json"),
        get_weixin_credentials_path(),
        str(mcp_config_file()),
        str(shared_root() / ".env"),
        str(shared_root() / "session_prefs.json"),
        str(shared_root() / "projects.json"),
        str(state_root() / "AGENT.md"),
        str(state_root() / "RULE.md"),
        str(state_root() / "BOOTSTRAP.md"),
        str(elearning_config),
        str(briefing_db(ensure=False).with_name("mailbox.json")),
        *(str(email_db) + suffix for suffix in ("", "-wal", "-shm", "-journal")),
    )}



def protected_credential_folders() -> set[str]:
    """Private connector files and Core lifecycle state, including migration copies."""
    from common.state_dir import briefing_db, shared_root
    user = briefing_db(ensure=False).parent.parent
    folders = {
        user / 'email', user / 'elearning', user / 'data', user / 'plugins',
        user / 'bills', user / 'todos', user / 'calendar', user / 'agent-hub', user / 'briefing' / 'elearning-sessions',
        user / '.stella-private-migrations',
        shared_root() / 'plugin-packages' / 'management',
    }
    # Historical directory migrations left retired data next to the active
    # directory. Keep these protected while new operations use the fixed root.
    folders.update(user.glob('.stella-migrate-*'))
    folders.update(user.glob('.stella-retired-*'))
    return {os.path.realpath(path) for path in folders}


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
    if is_elearning_credential_path(absolute_path):
        return True
    from common.state_dir import briefing_db
    user = os.path.realpath(briefing_db(ensure=False).parent.parent)
    for candidate in candidates:
        if candidate.startswith(user + '/'):
            first = candidate[len(user) + 1:].split('/')[0]
            if first.startswith(('.stella-migrate-', '.stella-retired-')):
                return True
    for folder in protected_credential_folders():
        if any(candidate == folder or candidate.startswith(folder + '/') for candidate in candidates):
            return True

    # 2. The credential file itself, following symlinks on both sides.
    return any(path.replace(os.sep, "/") in candidates for path in (protected_paths or protected_credential_paths()))
