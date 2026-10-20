"""Managed, nonblocking local CLI runs shared by print/exec adapters."""
from __future__ import annotations

import atexit
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any, Iterator

from domain.providers._local_runtime import new_run_id, sanitized_env
from domain.providers.base import ProviderAdapter


class ManagedCliProvider(ProviderAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._runs: dict[str, dict[str, Any]] = {}
        self._cleanup_registered = False

    @staticmethod
    def _stop(process):
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)],
                           capture_output=True, timeout=5, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)

    def _start_cli(self, argv: list[str], task: dict[str, Any], filename: str) -> dict[str, Any]:
        workspace = Path(task['workspacePath'])
        output = workspace / filename
        wall = float((task.get('budget') or {}).get('maxWallTime') or 120)
        if not 0 < wall <= 3600:
            raise ValueError('maxWallTime must be between 0 and 3600 seconds')
        try:
            with output.open('w', encoding='utf-8') as stream:
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream,
                                           stderr=subprocess.STDOUT, cwd=str(workspace),
                                           env=sanitized_env(), **({'process_group': 0} if os.name != 'nt' else {}))
        except OSError as exc:
            return {'status': 'rejected', 'error': {'code': 'start_failed', 'message': str(exc)}}
        run_ref = new_run_id(self.provider_local_id)
        run = {'process': process, 'status': 'running', 'outputPath': str(output),
               'lock': threading.RLock()}
        self._runs[run_ref] = run
        if not self._cleanup_registered:
            atexit.register(self.close)
            self._cleanup_registered = True

        def wait():
            try:
                process.wait(timeout=wall)
                self._stop(process)
                with run['lock']:
                    if run['status'] == 'running':
                        run['status'] = 'succeeded' if process.returncode == 0 else 'failed'
            except subprocess.TimeoutExpired:
                self._stop(process)
                with run['lock']:
                    run['status'] = 'outcome_unknown'
                    run['error'] = {'code': 'wall_time_exceeded'}
        threading.Thread(target=wait, name=f'hub-{run_ref}', daemon=True).start()
        return {'externalRunRef': run_ref, 'status': 'started'}

    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        run = self._runs.get(external_run_ref)
        if run is None:
            yield {'type': 'terminal', 'status': 'outcome_unknown', 'error': {'code': 'run_not_attached'}}
            return
        with run['lock']:
            status = run['status']
            if status == 'running':
                yield {'type': 'progress', 'message': 'CLI task is running'}
            else:
                yield {'type': 'terminal', 'status': status, 'outputPath': run['outputPath'],
                       'summary': 'CLI task finished', 'error': run.get('error')}

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        run = self._runs.get(external_run_ref)
        if run is None:
            return {'status': 'unknown'}
        with run['lock']:
            process = run['process']
            if process.poll() is not None:
                self._stop(process)
                if run['status'] == 'running':
                    run['status'] = 'succeeded' if process.returncode == 0 else 'failed'
                return {'status': 'already_finished'}
            self._stop(process)
            run['status'] = 'cancelled'
            return {'status': 'acknowledged'}

    def close(self):
        atexit.unregister(self.close)
        for run_ref in list(self._runs):
            self.request_cancel(run_ref)
