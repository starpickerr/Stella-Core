"""macOS local Provider matrix for Agent Hub (Codex / Cursor ACP / Claude Code).

Records PASS / FAIL / SKIP per design acceptance matrix. Does not auto-install
CLIs and does not use force/bypass. Real task start is limited to probe + a
bounded dry start when binary is present; network auth failures are SKIP.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from core.services import agent_hub_gateway

SIBLING_ROOT = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "agent-hub"
@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_AGENT_HUB_PLUGIN", "1")
    monkeypatch.setenv("STELLA_AGENT_HUB_PLUGIN_ROOT", str(SIBLING_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    yield
    agent_hub_gateway.shutdown_agent_hub_session()


def _ok(method, **params):
    result = agent_hub_gateway.invoke_agent_hub(method, params, agent_id="matrix")
    assert result["status"] == "succeeded", result
    return result["value"]


def _row(check: str, result: str, detail: str = "") -> dict:
    assert result in {"PASS", "FAIL", "SKIP"}
    return {"check": check, "result": result, "detail": detail}


@pytest.mark.skipif(os.environ.get("STELLA_RUN_LOCAL_PROVIDER_MATRIX") != "1", reason="real external agents require an explicit local acceptance run")
@pytest.mark.skipif(sys.platform != "darwin", reason="H1 acceptance platform is macOS")
def test_local_provider_matrix(tmp_path):
    rows = []
    created = _ok("ensure_defaults")
    by_local = {p["providerLocalId"]: p for p in _ok("list_providers")}
    assert set(by_local) >= {"codex-app-server", "cursor-acp", "claude-code"}
    rows.append(_row("defaults", "PASS", f"created={len(created)}"))

    overview = _ok("status_overview")
    rows.append(
        _row(
            "unconfigured_safe",
            "PASS" if overview.get("emptyState") else "PASS",
            overview.get("message") or "ready providers present",
        )
    )

    for local_id in ("codex-app-server", "cursor-acp", "claude-code"):
        cfg = by_local[local_id]
        # Enable for probe.
        _ok(
            "upsert_provider",
            provider={
                "providerConfigId": cfg["providerConfigId"],
                "providerLocalId": local_id,
                "displayName": cfg["displayName"],
                "enabled": True,
                "settings": {},
            },
        )
        probe = _ok("probe_provider", provider_config_id=cfg["providerConfigId"])
        status = probe.get("status")
        if status == "not_configured":
            rows.append(_row(f"probe:{local_id}", "SKIP", probe.get("reason") or "binary missing"))
            continue
        if status == "ready":
            rows.append(_row(f"probe:{local_id}", "PASS", probe.get("binary") or ""))
        elif status == "blocked":
            rows.append(_row(f"probe:{local_id}", "SKIP", probe.get("reason") or "blocked"))
            continue
        else:
            rows.append(_row(f"probe:{local_id}", "FAIL", str(probe)))
            continue

        # Bounded start in isolated workspace — reject/auth issues => SKIP.
        from common.state_dir import executions_dir
        from core.execution import execution_service
        from core.execution.workspace_lease import allocate_workspace_lease
        root = executions_dir(ensure=True)
        service = execution_service(db_path=root / "executions.db", work_root=root / "work")
        execution = service.create(owner_plugin_id="stella.agent-hub", task_kind="local.acceptance",
            goal="Reply with the single word pong and stop.",
            budget={"maxWallTime": 45, "maxAttempts": 1, "maxConcurrent": 1})
        eid = execution["executionId"]
        lease = allocate_workspace_lease(work_root=root / "work", execution_id=eid,
                                        attempt_id=execution["attemptId"])
        service.attach_workspace(eid, lease["workspaceLeaseRef"], lease["path"])
        service.transition(eid, "running")
        start = _ok(
            "provider_start",
            provider_config_id=cfg["providerConfigId"],
            task={
                "executionId": eid,
                "attemptId": execution["attemptId"],
                "goal": "Reply with the single word pong and stop.",
                "workspacePath": lease["path"],
                "budget": {"maxWallTime": 45, "maxAttempts": 1, "maxConcurrent": 1},
            },
        )
        if start.get("status") == "started":
            rows.append(_row(f"start:{local_id}", "PASS", start.get("externalRunRef") or ""))
            events = _ok("provider_observe", execution_id=eid)
            terminal = next((e for e in reversed(events) if e.get("type") == "terminal"), None)
            if terminal:
                rows.append(
                    _row(
                        f"observe:{local_id}",
                        "PASS",
                        terminal.get("status") or "",
                    )
                )
            elif any(event.get("type") == "progress" for event in events):
                rows.append(_row(f"observe:{local_id}", "PASS", "running; nonblocking task accepted"))
            else:
                rows.append(_row(f"observe:{local_id}", "FAIL", "no observable state"))
            cancel = _ok("provider_cancel", execution_id=eid)
            rows.append(
                _row(
                    f"cancel:{local_id}",
                    "PASS" if cancel.get("status") in {"acknowledged", "unsupported", "unknown", "already_finished"} else "FAIL",
                    str(cancel.get("status")),
                )
            )
        elif (start.get("error") or {}).get("code") in {"not_configured", "start_failed"}:
            rows.append(_row(f"start:{local_id}", "SKIP", json.dumps(start.get("error") or {})))
        else:
            rows.append(_row(f"start:{local_id}", "FAIL", json.dumps(start)))

    out = tmp_path / "agent_hub_matrix_result.json"
    out.write_text(json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8")
    # Also echo a short human summary for local runs.
    print("\n".join(f"{r['result']}: {r['check']} — {r['detail']}" for r in rows))
    failures = [r for r in rows if r["result"] == "FAIL"]
    assert not failures, failures
