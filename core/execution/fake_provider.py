"""Managed local fake Provider for H0 acceptance — no real CLI."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterator


class FakeLocalProvider:
    provider_local_id = "fake-local"

    def __init__(self, *, work_root: Path):
        self.work_root = Path(work_root)
        self._runs: dict[str, dict[str, Any]] = {}

    def describe(self) -> dict[str, Any]:
        return {
            "providerId": f"stella.agent-hub/{self.provider_local_id}",
            "contractVersion": "1",
            "taskKinds": ["local.echo"],
            "capabilities": {
                "streaming": True,
                "persistentSession": False,
                "reattach": False,
                "localOrRemote": "local",
                "artifacts": True,
            },
            "limits": {
                "filesystemWrite": "workspace",
                "network": False,
                "childProcesses": False,
            },
        }

    def probe(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "installed": True,
            "authenticated": True,
            "capabilities": self.describe()["capabilities"],
        }

    def start(self, task: dict[str, Any]) -> dict[str, Any]:
        run_ref = f"fake-{uuid.uuid4().hex[:12]}"
        workspace = Path(task["workspacePath"])
        workspace.mkdir(parents=True, exist_ok=True)
        out = workspace / "result.txt"
        out.write_text("hello\n", encoding="utf-8")
        self._runs[run_ref] = {
            "executionId": task["executionId"],
            "status": "succeeded",
            "path": str(out),
        }
        return {"externalRunRef": run_ref, "status": "started"}

    def observe(self, external_run_ref: str) -> Iterator[dict[str, Any]]:
        run = self._runs.get(external_run_ref)
        if run is None:
            yield {"type": "terminal", "status": "failed", "error": {"code": "unknown_run"}}
            return
        yield {"type": "progress", "message": "writing"}
        yield {
            "type": "terminal",
            "status": run["status"],
            "summary": "echo complete",
            "outputPath": run["path"],
        }

    def request_cancel(self, external_run_ref: str) -> dict[str, Any]:
        if external_run_ref not in self._runs:
            return {"status": "unknown"}
        return {"status": "acknowledged"}
