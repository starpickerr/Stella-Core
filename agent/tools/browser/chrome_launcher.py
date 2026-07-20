"""Spawn a system Chrome/Edge with a DevTools debugging port for CDP control.

Why this exists: driving a system browser via Playwright's
``chromium.launch(channel="chrome")`` makes the app *take over* another app's
process, which on macOS triggers a TCC "Automation" permission prompt and a
multi-second (sometimes 100s+) stall on first use. Launching Chrome ourselves
with ``--remote-debugging-port`` and attaching via ``connect_over_cdp`` avoids
that entirely — from the OS's view it's just a process listening on a local
port — and matches how Codex / Claude Code drive the user's real browser.

The launched process uses an isolated ``--user-data-dir`` so it never fights
the user's day-to-day browser profile, while still persisting login state
across sessions inside that dir.
"""

import os
import sys
import time
import socket
import subprocess
import urllib.request
from typing import Optional, List

from common.log import logger


class ChromeLauncher:
    """Own the lifecycle of a debugging-enabled Chrome/Edge child process."""

    def __init__(self, executable: str, user_data_dir: str,
                 extra_args: Optional[List[str]] = None,
                 headless: bool = False):
        self._executable = executable
        self._user_data_dir = user_data_dir
        self._extra_args = extra_args or []
        self._headless = headless
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None

    @property
    def endpoint(self) -> str:
        """CDP HTTP endpoint (only valid after a successful launch())."""
        return f"http://127.0.0.1:{self._port}" if self._port else ""

    @staticmethod
    def _free_port() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]
        finally:
            s.close()

    def launch(self, ready_timeout: float = 25.0) -> str:
        """Spawn Chrome and block until its CDP endpoint answers.

        Returns the CDP endpoint URL. Raises RuntimeError if the endpoint never
        comes up (the child process is killed in that case).
        """
        os.makedirs(self._user_data_dir, exist_ok=True)
        self._port = self._free_port()

        args = [
            self._executable,
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._user_data_dir}",
            # Trim first-run overhead and background chatter for faster starts.
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-features=Translate,OptimizationHints",
            # A blank first tab keeps startup cheap and predictable.
            "about:blank",
        ]
        if self._headless:
            args.insert(1, "--headless=new")
        args[1:1] = self._extra_args

        popen_kwargs = {}
        if sys.platform == "win32":
            # Detach from any console and never flash a window on Windows.
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        else:
            # New session so the child isn't tied to the parent's controlling
            # terminal / process group (clean teardown, no signal bleed).
            popen_kwargs["start_new_session"] = True

        logger.info(f"[Browser] Spawning {os.path.basename(self._executable)} "
                    f"on CDP port {self._port} (profile={self._user_data_dir})")
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs,
        )

        if not self._wait_ready(ready_timeout):
            self.close()
            raise RuntimeError(
                f"Chrome did not expose a CDP endpoint on port {self._port} "
                f"within {ready_timeout:.0f}s"
            )
        return self.endpoint

    def _wait_ready(self, timeout: float) -> bool:
        """Poll DevTools /json/version until Chrome is listening (or times out)."""
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{self._port}/json/version"
        while time.time() < deadline:
            # Bail out early if the process died on startup.
            if self._proc and self._proc.poll() is not None:
                logger.error(
                    f"[Browser] Chrome exited early (code={self._proc.returncode}) "
                    "before opening the CDP port"
                )
                return False
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.15)
        return False

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self):
        """Terminate the spawned Chrome process (idempotent)."""
        proc = self._proc
        self._proc = None
        self._port = None
        if proc is None:
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception as e:
            logger.debug(f"[Browser] error terminating Chrome process: {e}")
