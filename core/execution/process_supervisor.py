"""Track managed process trees for H0 executions; revoke kills the group."""

from __future__ import annotations

import subprocess
import threading
from typing import Any


class ProcessSupervisor:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._leases: dict[str, subprocess.Popen] = {}

    def register(self, lease_id: str, process: subprocess.Popen) -> None:
        if not lease_id:
            raise ValueError("lease_id required")
        with self._lock:
            existing = self._leases.get(lease_id)
            if existing is not None and existing.poll() is None:
                raise ValueError(f"lease already has a live process: {lease_id}")
            self._leases[lease_id] = process

    def revoke(self, lease_id: str) -> dict[str, Any]:
        with self._lock:
            process = self._leases.pop(lease_id, None)
        if process is None:
            return {"status": "unknown", "leaseId": lease_id}
        self._stop(process)
        return {"status": "stopped", "leaseId": lease_id, "returncode": process.poll()}

    def revoke_all(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(self._leases)
        return [self.revoke(lease_id) for lease_id in ids]

    @staticmethod
    def _stop(process: subprocess.Popen) -> None:
        from common.process_tree import stop_process_tree
        stop_process_tree(process)
