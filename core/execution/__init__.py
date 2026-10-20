"""H0 public execution foundation: authoritative status, leases, artifacts."""

import threading
from pathlib import Path

from core.execution.service import ExecutionService, TerminalConflict

__all__ = ["ExecutionService", "TerminalConflict"]



_SERVICES: dict[str, ExecutionService] = {}
_SERVICES_LOCK = threading.Lock()


def execution_service(*, db_path: Path, work_root: Path) -> ExecutionService:
    """Recover a user's execution store once at process startup, not on every query."""
    key = str(Path(db_path).resolve())
    with _SERVICES_LOCK:
        if key not in _SERVICES:
            _SERVICES[key] = ExecutionService(db_path=db_path, work_root=work_root)
        return _SERVICES[key]
