"""Public H0 execution API: create/get/list/watch/requestCancel/reconcile."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterator

from core.execution.store import TERMINAL, ExecutionStore, TerminalStoreConflict

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancel_requested", "cancelled", "failed", "outcome_unknown"}),
    "running": frozenset({
        "waiting_approval",
        "succeeded",
        "failed",
        "cancelled",
        "cancel_requested",
        "interrupted",
        "outcome_unknown",
    }),
    "waiting_approval": frozenset({
        "running",
        "cancel_requested",
        "cancelled",
        "failed",
        "succeeded",
        "outcome_unknown",
    }),
    "cancel_requested": frozenset({"cancelled", "succeeded", "failed", "outcome_unknown"}),
    "interrupted": frozenset({"running", "succeeded", "failed", "cancelled", "outcome_unknown"}),
    "outcome_unknown": frozenset({"running", "succeeded", "failed", "cancelled", "interrupted"}),
}


class TerminalConflict(RuntimeError):
    """Raised when a terminal execution rejects further mutations."""


class ExecutionService:
    def __init__(self, *, db_path: Path, work_root: Path):
        self.db_path = Path(db_path)
        self.work_root = Path(work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self._store = ExecutionStore(self.db_path)
        self._store.recover_active_to_unknown()

    def create(
        self,
        *,
        owner_plugin_id: str,
        task_kind: str,
        goal: str,
        budget: dict[str, Any],
        acceptance: dict[str, Any] | None = None,
        parent_execution_id: str | None = None,
        provider_owner_plugin_id: str | None = None,
        grant_ref: str | None = None,
        policy_digest: str | None = None,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        if not owner_plugin_id or not task_kind or not goal:
            raise ValueError("owner_plugin_id, task_kind and goal are required")
        for key in ("maxWallTime", "maxAttempts", "maxConcurrent"):
            if key not in budget:
                raise ValueError(f"budget.{key} is required")
        eid = execution_id or f"exec-{uuid.uuid4().hex}"
        attempt = f"att-{uuid.uuid4().hex[:12]}"
        return self._store.insert(
            {
                "execution_id": eid,
                "parent_execution_id": parent_execution_id,
                "attempt_id": attempt,
                "owner_plugin_id": owner_plugin_id,
                "provider_owner_plugin_id": provider_owner_plugin_id or owner_plugin_id,
                "task_kind": task_kind,
                "goal": goal,
                "acceptance": acceptance or {},
                "status": "queued",
                "budget": budget,
                "grant_ref": grant_ref,
                "policy_digest": policy_digest,
            }
        )

    def get(self, execution_id: str) -> dict[str, Any]:
        row = self._store.get(execution_id)
        if row is None:
            raise KeyError(execution_id)
        return row

    def list(self, *, owner_plugin_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._store.list(owner_plugin_id=owner_plugin_id, limit=limit)

    def watch(self, execution_id: str, *, after_sequence: int = 0) -> Iterator[dict[str, Any]]:
        row = self.get(execution_id)
        yield {
            "kind": "snapshot",
            "status": row["status"],
            "executionId": execution_id,
            "artifactRefs": row["artifactRefs"],
            "summary": row["summary"],
        }
        for event in self._store.events(execution_id, after_sequence=after_sequence):
            yield {"kind": "event", **event}
        # Final snapshot after events for callers that only care about status.
        latest = self.get(execution_id)
        yield {
            "kind": "snapshot",
            "status": latest["status"],
            "executionId": execution_id,
            "artifactRefs": latest["artifactRefs"],
            "summary": latest["summary"],
        }

    def request_cancel(self, execution_id: str) -> dict[str, Any]:
        try:
            return self._store.set_cancel_requested(execution_id)
        except TerminalStoreConflict as exc:
            raise TerminalConflict(str(exc)) from exc

    def transition(
        self,
        execution_id: str,
        status: str,
        *,
        summary: str | None = None,
        error: dict | None = None,
    ) -> dict[str, Any]:
        row = self.get(execution_id)
        current = row["status"]
        if current in TERMINAL:
            raise TerminalConflict(f"terminal status {current!r} rejects {status!r}")
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if status not in allowed and status != current:
            raise ValueError(f"illegal transition {current!r} -> {status!r}")
        try:
            return self._store.update_status(execution_id, status, summary=summary, error=error)
        except TerminalStoreConflict as exc:
            raise TerminalConflict(str(exc)) from exc

    def append_event(self, execution_id: str, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._store.append_event(execution_id, type_, payload)
        except TerminalStoreConflict as exc:
            raise TerminalConflict(str(exc)) from exc

    def attach_workspace(self, execution_id: str, lease_ref: str, path: str) -> None:
        row = self.get(execution_id)
        if row["status"] in TERMINAL:
            raise TerminalConflict(f"terminal status {row['status']!r} rejects workspace attach")
        self._store.attach_workspace(execution_id, lease_ref, path)

    def attach_artifacts(self, execution_id: str, refs: list[str]) -> None:
        try:
            self._store.attach_artifacts(execution_id, refs)
        except TerminalStoreConflict as exc:
            raise TerminalConflict(str(exc)) from exc

    def reconcile(self, execution_id: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
        """Authorized recovery — never invents success; may reattach to running."""
        row = self.get(execution_id)
        if row["status"] in TERMINAL:
            return row
        if row["status"] not in {"outcome_unknown", "interrupted", "cancel_requested"}:
            raise ValueError(f"reconcile not applicable for status {row['status']!r}")
        external = (evidence or {}).get("externalStatus")
        if external == "still_running":
            return self.transition(execution_id, "running")
        if external in {"succeeded", "failed", "cancelled"}:
            return self.transition(
                execution_id,
                external,
                summary=(evidence or {}).get("summary"),
                error=(evidence or {}).get("error"),
            )
        # Insufficient evidence — keep unknown.
        self.append_event(execution_id, "reconcile", {"result": "insufficient_evidence", "evidence": evidence})
        return self.get(execution_id)

    def blind_start(self, execution_id: str) -> None:
        """Explicitly refused: recovery must go through reconcile, not a new start."""
        row = self.get(execution_id)
        if row["status"] in {"outcome_unknown", "interrupted"}:
            raise ValueError("blind start refused; reconcile with evidence first")
        raise ValueError(f"blind start refused for status {row['status']!r}")
