"""Plugin API 1.0 structural validation aligned with contracts/v1 Schema."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

_ORIGINS = frozenset({"ui", "tool", "job", "plugin", "system"})
_RESULT_STATUS = frozenset({"succeeded", "failed", "cancelled", "pending", "unknown"})
_SIDE_EFFECTS = frozenset({"none", "committed", "unknown"})


class ContractError(ValueError):
    pass


def validate_host_context(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ContractError("HostContext must be an object")
    required = (
        "userId",
        "callerPrincipal",
        "instanceId",
        "generation",
        "origin",
        "delegationChain",
        "grantRef",
        "traceId",
        "invocationRef",
    )
    for key in required:
        if key not in data:
            raise ContractError(f"HostContext missing {key}")
    if "callerPluginId" not in data:
        raise ContractError("HostContext missing callerPluginId")
    if data["origin"] not in _ORIGINS:
        raise ContractError(f"invalid origin: {data['origin']}")
    if not isinstance(data["generation"], int) or data["generation"] < 1:
        raise ContractError("generation must be positive int")
    if not isinstance(data["delegationChain"], list):
        raise ContractError("delegationChain must be an array")
    for key in (
        "userId",
        "callerPrincipal",
        "instanceId",
        "grantRef",
        "traceId",
        "invocationRef",
    ):
        if not isinstance(data[key], str) or not data[key]:
            raise ContractError(f"{key} must be non-empty string")
    return data


def validate_invoke_params(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ContractError("InvokeParams must be an object")
    for key in ("contract", "method", "input", "deadline", "context"):
        if key not in data:
            raise ContractError(f"InvokeParams missing {key}")
    if not isinstance(data["contract"], str) or "@" not in data["contract"]:
        raise ContractError("contract must look like name@major")
    if not isinstance(data["method"], str) or not data["method"]:
        raise ContractError("method must be non-empty string")
    if not isinstance(data["input"], dict):
        raise ContractError("input must be an object")
    if not isinstance(data["deadline"], str) or not data["deadline"]:
        raise ContractError("deadline must be RFC3339 string")
    # Reject expired deadlines at validation time when parseable.
    try:
        deadline = datetime.fromisoformat(data["deadline"].replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            raise ContractError("deadline must include timezone")
        if deadline < datetime.now(timezone.utc):
            raise ContractError("deadline expired")
    except ValueError as exc:
        raise ContractError(f"invalid deadline: {exc}") from exc
    validate_host_context(data["context"])
    if "idempotencyKey" in data and data["idempotencyKey"] is not None:
        if not isinstance(data["idempotencyKey"], str) or not data["idempotencyKey"]:
            raise ContractError("idempotencyKey must be non-empty string when set")
    return data


def validate_operation_result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ContractError("OperationResult must be an object")
    if data.get("status") not in _RESULT_STATUS:
        raise ContractError(f"invalid status: {data.get('status')}")
    if data.get("sideEffects") not in _SIDE_EFFECTS:
        raise ContractError(f"invalid sideEffects: {data.get('sideEffects')}")
    if data["status"] == "pending" and not data.get("operationId"):
        raise ContractError("pending result requires operationId")
    if data["status"] == "unknown" and data.get("sideEffects") == "none":
        raise ContractError("unknown must not claim sideEffects=none")
    if data["status"] == "failed" and not isinstance(data.get("error"), dict):
        raise ContractError("failed result requires error object")
    return data


def build_host_context(
    *,
    user_id: str,
    instance_id: str,
    generation: int,
    origin: str,
    grant_ref: str,
    caller_principal: str | None = None,
    caller_plugin_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    delegation_chain: list | None = None,
    trace_id: str | None = None,
    invocation_ref: str | None = None,
) -> dict[str, Any]:
    ctx = {
        "userId": user_id,
        "callerPrincipal": caller_principal or f"user:{user_id}",
        "callerPluginId": caller_plugin_id,
        "instanceId": instance_id,
        "generation": generation,
        "origin": origin,
        "delegationChain": list(delegation_chain or []),
        "grantRef": grant_ref,
        "traceId": trace_id or uuid.uuid4().hex,
        "invocationRef": invocation_ref or uuid.uuid4().hex,
    }
    if agent_id is not None:
        ctx["agentId"] = agent_id
    if session_id is not None:
        ctx["sessionId"] = session_id
    if run_id is not None:
        ctx["runId"] = run_id
    if job_id is not None:
        ctx["jobId"] = job_id
    return ctx


def build_invoke_params(
    *,
    contract: str,
    method: str,
    input_payload: Mapping[str, Any],
    context: Mapping[str, Any],
    deadline: datetime,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    if deadline.tzinfo is None:
        raise ContractError("deadline must be timezone-aware")
    params: dict[str, Any] = {
        "contract": contract,
        "method": method,
        "input": dict(input_payload),
        "deadline": deadline.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "context": dict(context),
    }
    if idempotency_key is not None:
        params["idempotencyKey"] = idempotency_key
    return validate_invoke_params(params)
