"""Run browser checks against a private renderer and clean its process group."""
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_runtime import npm_path, python_path

ROOT = Path(__file__).resolve().parent.parent


def run_server(server, client, port=None):
    with socket.socket() as reservation:
        try:
            reservation.bind(('127.0.0.1', port or 0))
        except OSError as exc:
            raise RuntimeError('renderer port occupied') from exc
        port = reservation.getsockname()[1]
    env = dict(os.environ, STELLA_TEST_URL=f'http://127.0.0.1:{port}')
    command = [value.replace('{port}', str(port)) for value in server]
    with tempfile.TemporaryFile(mode='w+') as output:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output, stderr=output, start_new_session=True)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output.seek(0)
                    raise RuntimeError('renderer exited: ' + output.read()[-2000:])
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('renderer startup timeout')
            if process.poll() is not None:
                raise RuntimeError('renderer exited before browser check')
            return subprocess.run(client, cwd=ROOT, env=env, timeout=90).returncode
        finally:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                process.wait(timeout=5)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()


if __name__ == '__main__':
    scripts = ['tests/ui_smoke.py', 'tests/ui_briefing.py', 'tests/ui_tasks.py', 'tests/ui_apple_calendar.py',
               'tests/ui_apple_settings.py', 'tests/ui_embedded_agents.py']
    scripts = [path for path in scripts if (ROOT / path).is_file()]
    checks = [str(python_path(ROOT)), '-c', 'import runpy; ' + '; '.join(
        f'runpy.run_path({path!r})' for path in scripts)]
    sys.exit(run_server([npm_path(), '--prefix', 'desktop', 'run', 'dev:renderer', '--', '--host', '127.0.0.1', '--port', '{port}'], checks))
