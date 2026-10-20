"""Minimal JSON-RPC over stdio helper for local Agent CLIs.

Does not install binaries, does not inherit full user environment, and never
uses force/bypass flags. Probe must not start a durable task.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any


def sanitized_env() -> dict[str, str]:
    """Minimal env: PATH + locale only — no credential dump."""
    keep = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "HOME", "TMPDIR", "TEMP", "TMP")
    env = {k: v for k in keep if (v := os.environ.get(k))}
    # Allow explicit auth markers without copying secrets wholesale.
    for key in ("CODEX_HOME", "CURSOR_API_KEY", "ANTHROPIC_API_KEY"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_version_probe(argv: list[str], *, timeout: float = 8.0) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=sanitized_env(),
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "binary_missing"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "probe_timeout"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    out = (result.stdout or result.stderr or "").strip()
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "output": out[:500],
    }


class StdioJsonRpcSession:
    """Short-lived stdio JSON-RPC session for a single delegated run."""

    def __init__(self, argv: list[str], *, cwd: str | None = None):
        self.argv = list(argv)
        self.cwd = cwd
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next_id = 1

    def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.cwd,
            env=sanitized_env(),
            start_new_session=True,
        )

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0) -> dict[str, Any]:
        self.start()
        assert self._proc and self._proc.stdin and self._proc.stdout
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
            deadline = timeout
            # Blocking readline with process-level timeout via wait thread.
            line_holder: dict[str, str | None] = {"line": None}

            def _read() -> None:
                assert self._proc and self._proc.stdout
                line_holder["line"] = self._proc.stdout.readline()

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            reader.join(timeout=deadline)
            if reader.is_alive():
                self.close()
                raise TimeoutError(f"json-rpc timeout on {method}")
            line = line_holder["line"] or ""
            if not line:
                raise RuntimeError("provider closed stdout")
            data = json.loads(line)
            if "error" in data:
                raise RuntimeError(json.dumps(data["error"], ensure_ascii=False))
            return data.get("result") or {}

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass


def write_goal_file(workspace: Path, goal: str) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / ".stella-agent-hub-goal.md"
    path.write_text(goal.strip() + "\n", encoding="utf-8")
    return path


def new_run_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
