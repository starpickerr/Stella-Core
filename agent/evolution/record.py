"""Self-evolution record log.

Session-level evolutions are appended to their OWN per-day file under
``memory/evolution/YYYY-MM-DD.md`` (separate from the nightly Deep Dream diary
in ``memory/dreams/``). Each day's file accumulates one short section per
evolution pass — tagged with a timestamp and a backup id for undo — so the
memory UI can surface "what the agent learned/changed today" on one timeline
without ever mixing into the dream diary or the main conversation memory.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from common.log import logger


def _evolution_dir(workspace_dir: Path, user_id: Optional[str] = None) -> Path:
    from common.state_dir import user_root_for_workspace

    return user_root_for_workspace(workspace_dir, user_id) / "memory" / "evolution"


def append_session_evolution(
    workspace_dir: Path,
    summary: str,
    backup_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Append a session-evolution entry to today's evolution log."""
    if not summary or not summary.strip():
        return
    try:
        from core.services.memory_facade import MemoryPort
        today = datetime.now().strftime('%Y-%m-%d')
        ts = datetime.now().strftime('%H:%M')
        body = f"\n## {ts}\n\n{summary.strip()}\n"
        if backup_id:
            body += f"\n_backup_id: {backup_id}_\n"
        MemoryPort()._call('write', path=f'memory/evolution/{today}.md', content=body, append=True)
    except Exception as e:
        logger.warning(f"[Evolution] Failed to record session evolution: {e}")
