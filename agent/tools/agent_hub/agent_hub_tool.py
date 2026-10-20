"""Delegate professional tasks via Agent Hub — returns executionId immediately."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


class AgentHubTool(BaseTool):
    name: str = "agent_hub"
    description: str = (
        "外部专业 Agent 协作（Agent Hub）：向 Codex / Cursor ACP / Claude Code 委托任务。\n"
        "长任务立即返回 executionId，不阻塞对话等待结束。\n\n"
        "actions:\n"
        "- submit: 提交目标与验收条件，返回 executionId\n"
        "- status: 查询 executionId 状态与事件\n"
        "- cancel: 请求取消\n"
        "- continue: 在支持时继续（否则 UNSUPPORTED）\n"
        "- providers: 列出/探测已配置 Provider\n"
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["submit", "status", "cancel", "continue", "providers"],
            },
            "goal": {"type": "string", "description": "submit: 任务目标"},
            "task_kind": {
                "type": "string",
                "description": "submit: 开放任务类型，如 coding.task / research.report",
            },
            "acceptance": {"type": "object", "description": "submit: 验收条件"},
            "provider_config_id": {"type": "string"},
            "provider_local_id": {
                "type": "string",
                "enum": [
                    "codex-app-server",
                    "codex-cli",
                    "cursor-acp",
                    "cursor-cli",
                    "claude-code",
                ],
            },
            "agent_id": {
                "type": "string",
                "enum": ["codex", "cursor", "claude-code"],
                "description": "submit: 按 Agent 身份选择（可与 access_mode 组合）",
            },
            "access_mode": {
                "type": "string",
                "enum": ["cli", "app-server", "acp"],
                "description": "submit: 接入方式；与 agent_id 一起使用",
            },
            "execution_id": {"type": "string"},
            "max_wall_time": {"type": "integer", "minimum": 5, "maximum": 3600},
        },
        "required": ["action"],
    }

    def is_available(self) -> bool:
        try:
            from core.services.agent_hub_gateway import agent_hub_plugin_enabled

            return agent_hub_plugin_enabled()
        except Exception:
            return False

    def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action")
        try:
            if action == "providers":
                return ToolResult.success(self._providers())
            if action == "submit":
                return ToolResult.success(self._submit(kwargs))
            if action == "status":
                return ToolResult.success(self._status(kwargs["execution_id"]))
            if action == "cancel":
                return ToolResult.success(self._cancel(kwargs["execution_id"]))
            if action == "continue":
                return ToolResult.fail(
                    {"code": "UNSUPPORTED_CAPABILITY", "capability": "continue"}
                )
            return ToolResult.fail(f"unknown action: {action}")
        except Exception as exc:
            logger.exception("[agent_hub] %s failed", action)
            return ToolResult.fail(str(exc))

    def _providers(self) -> dict[str, Any]:
        from core.services import agent_hub_gateway

        agent_hub_gateway.apply_user_preferences()
        overview = agent_hub_gateway.invoke_ok("status_overview")
        for row in overview.get("providers") or []:
            if not row.get("enabled"):
                continue
            try:
                agent_hub_gateway.invoke_ok(
                    "probe_provider", {"provider_config_id": row["providerConfigId"]}
                )
            except Exception:
                continue
        return agent_hub_gateway.invoke_ok("status_overview")

    def _execution_service(self):
        from common.state_dir import executions_dir
        from core.execution.service import ExecutionService

        root = executions_dir(ensure=True)
        return ExecutionService(db_path=root / "executions.db", work_root=root / "work")

    def _submit(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        from core.execution.artifacts import seal_artifact
        from core.execution.workspace_lease import allocate_workspace_lease
        from core.services import agent_hub_gateway

        goal = (kwargs.get("goal") or "").strip()
        if not goal:
            raise ValueError("goal is required for submit")
        task_kind = kwargs.get("task_kind") or "general.delegate"
        wall = int(kwargs.get("max_wall_time") or 180)
        svc = self._execution_service()
        created = svc.create(
            owner_plugin_id="stella.agent-hub",
            task_kind=task_kind,
            goal=goal,
            budget={"maxWallTime": wall, "maxAttempts": 1, "maxConcurrent": 1},
            acceptance=kwargs.get("acceptance") or {},
        )
        eid = created["executionId"]
        # Select provider (may raise if none ready — still return executionId queued).
        selector = {}
        if kwargs.get("provider_config_id"):
            selector["providerConfigId"] = kwargs["provider_config_id"]
        if kwargs.get("provider_local_id"):
            selector["providerLocalId"] = kwargs["provider_local_id"]
        if kwargs.get("agent_id"):
            selector["agentId"] = kwargs["agent_id"]
        if kwargs.get("access_mode"):
            selector["accessMode"] = kwargs["access_mode"]
        try:
            agent_hub_gateway.apply_user_preferences()
            provider = agent_hub_gateway.invoke_ok(
                "select_provider",
                {
                    "selector": agent_hub_gateway.resolve_provider_selector(selector or None)
                    or None
                },
            )
        except Exception as exc:
            svc.transition(eid, "failed", summary="no ready provider", error={"message": str(exc)})
            return {
                "executionId": eid,
                "status": "failed",
                "error": {"code": "no_provider", "message": str(exc)},
            }

        lease = allocate_workspace_lease(
            work_root=Path(svc.work_root),
            execution_id=eid,
            attempt_id=created["attemptId"],
            source_project=None,
        )
        svc.attach_workspace(eid, lease["workspaceLeaseRef"], lease["path"])
        svc.transition(eid, "running")
        start = agent_hub_gateway.invoke_ok(
            "provider_start",
            {
                "provider_config_id": provider["providerConfigId"],
                "task": {
                    "executionId": eid,
                    "attemptId": created["attemptId"],
                    "goal": goal,
                    "taskKind": task_kind,
                    "workspacePath": lease["path"],
                    "workspaceLeaseRef": lease["workspaceLeaseRef"],
                    "budget": created["budget"],
                    "acceptance": created.get("acceptance") or {},
                },
            },
        )
        if start.get("status") != "started":
            err = start.get("error") or {"message": "provider rejected start"}
            svc.transition(eid, "failed", summary="provider start rejected", error=err)
            return {"executionId": eid, "status": "failed", "error": err, "provider": provider}

        # Non-blocking contract: observe once in-process for short providers; long runs stay running.
        try:
            events = agent_hub_gateway.invoke_ok("provider_observe", {"execution_id": eid})
        except Exception as exc:
            logger.warning("[agent_hub] observe deferred: %s", exc)
            events = []
        terminal = next((e for e in reversed(events or []) if e.get("type") == "terminal"), None)
        if terminal and terminal.get("status") in {"succeeded", "failed", "cancelled"}:
            out = terminal.get("outputPath")
            refs = []
            if out and Path(out).is_file():
                art = seal_artifact(
                    store_root=Path(svc.work_root).parent / "artifacts",
                    source_path=out,
                    execution_id=eid,
                )
                refs.append(art["artifactRef"])
                svc.attach_artifacts(eid, refs)
            svc.transition(
                eid,
                terminal["status"],
                summary=terminal.get("summary"),
                error=terminal.get("error"),
            )
        elif terminal and terminal.get("status") == "outcome_unknown":
            svc.transition(eid, "outcome_unknown", summary=terminal.get("summary"))
        # else leave running for later status/cancel/reconcile
        row = svc.get(eid)
        return {
            "executionId": eid,
            "status": row["status"],
            "providerConfigId": provider["providerConfigId"],
            "providerLocalId": provider["providerLocalId"],
            "externalRunRef": start.get("externalRunRef"),
            "artifactRefs": row.get("artifactRefs") or [],
        }

    def _status(self, execution_id: str) -> dict[str, Any]:
        if not execution_id:
            raise ValueError("execution_id required")
        svc = self._execution_service()
        row = svc.get(execution_id)
        events = list(svc.watch(execution_id))
        mapping = None
        try:
            from core.services import agent_hub_gateway

            mapping = agent_hub_gateway.invoke_ok(
                "get_external_run", {"execution_id": execution_id}
            )
        except Exception:
            mapping = None
        return {"execution": row, "watch": events, "external": mapping}

    def _cancel(self, execution_id: str) -> dict[str, Any]:
        if not execution_id:
            raise ValueError("execution_id required")
        svc = self._execution_service()
        ack = svc.request_cancel(execution_id)
        provider_ack = {"status": "unknown"}
        try:
            from core.services import agent_hub_gateway

            provider_ack = agent_hub_gateway.invoke_ok(
                "provider_cancel", {"execution_id": execution_id}
            )
        except Exception as exc:
            provider_ack = {"status": "error", "message": str(exc)}
        return {"execution": ack, "provider": provider_ack}
