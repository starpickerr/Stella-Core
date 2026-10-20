"""Reap process groups owned by a managed runner, including orphaned children."""
from __future__ import annotations

import os
import signal
import subprocess


def _session_groups(session_id: int) -> set[int]:
    groups = {session_id}
    try:
        result = subprocess.run(['/bin/ps', '-A', '-o', 'pid='], capture_output=True,
                                text=True, timeout=2, check=False)
        for value in result.stdout.split():
            try:
                pid = int(value)
                if os.getsid(pid) == session_id:
                    groups.add(os.getpgid(pid))
            except (ValueError, ProcessLookupError, PermissionError):
                continue
    except (OSError, subprocess.TimeoutExpired):
        pass
    return groups


def stop_process_tree(process, *, owned_session: bool = False) -> None:
    if os.name == 'nt':
        if process.poll() is None:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                           capture_output=True, timeout=5, check=False)
    else:
        groups = _session_groups(process.pid) if owned_session else {process.pid}
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def reap_runner_session(process) -> None:
    process.wait()
    stop_process_tree(process, owned_session=True)
