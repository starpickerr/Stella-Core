"""Agent Hub domain service — provider configs, probe, mapping; Core owns execution status."""

from __future__ import annotations

import uuid
from typing import Any

from domain.providers import DEFAULT_CATALOG, get_adapter, resolve_identity
from domain.store import AgentHubStore


class ProviderNotFound(KeyError):
    pass


class AgentHubService:
    def __init__(self, store: AgentHubStore):
        self.store = store
        self._run_adapters = {}

    def list_catalog(self) -> list[dict[str, Any]]:
        return list(DEFAULT_CATALOG)

    def list_providers(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        return self.store.list_providers(enabled_only=enabled_only)

    def get_provider(self, provider_config_id: str) -> dict[str, Any]:
        row = self.store.get_provider(provider_config_id)
        if row is None:
            raise ProviderNotFound(provider_config_id)
        return row

    def upsert_provider(self, provider: dict[str, Any]) -> dict[str, Any]:
        local_id = provider.get("providerLocalId")
        if local_id not in {c["providerLocalId"] for c in DEFAULT_CATALOG}:
            raise ValueError(f"unsupported providerLocalId: {local_id}")
        agent_id, access_mode, _ = resolve_identity(local_id)
        config_id = provider.get("providerConfigId") or f"pcfg-{uuid.uuid4().hex[:12]}"
        catalog_row = next(c for c in DEFAULT_CATALOG if c["providerLocalId"] == local_id)
        display = provider.get("displayName") or catalog_row["displayName"]
        return self.store.upsert_provider(
            {
                "providerConfigId": config_id,
                "providerLocalId": local_id,
                "agentId": provider.get("agentId") or agent_id,
                "accessMode": provider.get("accessMode") or access_mode,
                "displayName": display,
                "binaryPath": provider.get("binaryPath"),
                "enabled": provider.get("enabled", True),
                "settings": provider.get("settings") or {},
                "lastProbe": provider.get("lastProbe"),
            }
        )

    def delete_provider(self, provider_config_id: str) -> dict[str, Any]:
        ok = self.store.delete_provider(provider_config_id)
        if not ok:
            raise ProviderNotFound(provider_config_id)
        return {"deleted": True, "providerConfigId": provider_config_id}

    def probe_provider(self, provider_config_id: str) -> dict[str, Any]:
        row = self.get_provider(provider_config_id)
        adapter = get_adapter(
            row["providerLocalId"],
            binary_path=row.get("binaryPath"),
            settings=row.get("settings") or {},
        )
        probe = adapter.probe()
        describe = adapter.describe()
        result = {**probe, "describe": describe, "providerConfigId": provider_config_id}
        self.store.save_probe(provider_config_id, result)
        return result

    def ensure_defaults(self) -> list[dict[str, Any]]:
        """Create disabled placeholder configs for each built-in provider if missing."""
        existing = {p["providerLocalId"] for p in self.store.list_providers()}
        created = []
        for item in DEFAULT_CATALOG:
            if item["providerLocalId"] in existing:
                continue
            created.append(
                self.upsert_provider(
                    {
                        "providerLocalId": item["providerLocalId"],
                        "agentId": item.get("agentId"),
                        "accessMode": item.get("accessMode"),
                        "displayName": item["displayName"],
                        "enabled": False,
                        "settings": {},
                    }
                )
            )
        return created

    def status_overview(self) -> dict[str, Any]:
        providers = self.list_providers()
        configured = [
            p
            for p in providers
            if p.get("enabled") and (p.get("lastProbe") or {}).get("status") == "ready"
        ]
        return {
            "configured": bool(configured),
            "providerCount": len(providers),
            "readyCount": len(configured),
            "providers": providers,
            "emptyState": not configured,
            "message": None
            if configured
            else "尚未配置可用的外部 Provider（Codex / Cursor ACP / Claude Code）。未配置不影响其他功能。",
        }

    def select_provider(self, selector: dict[str, Any] | None = None) -> dict[str, Any]:
        """User explicit → agentId(+accessMode) → first ready enabled."""
        selector = selector or {}
        if config_id := selector.get("providerConfigId"):
            return self.get_provider(config_id)
        local_id = selector.get("providerLocalId")
        agent_id = selector.get("agentId")
        access_mode = selector.get("accessMode")
        providers = self.list_providers(enabled_only=True)
        if local_id:
            for row in providers:
                if row["providerLocalId"] == local_id:
                    return row
            raise ProviderNotFound(local_id)
        if agent_id:
            matches = [row for row in providers if row.get("agentId") == agent_id]
            if access_mode:
                matches = [row for row in matches if row.get("accessMode") == access_mode]
            for row in matches:
                probe = row.get("lastProbe") or {}
                if probe.get("status") == "ready":
                    return row
            for row in matches:
                probe = self.probe_provider(row["providerConfigId"])
                if probe.get("status") == "ready":
                    return self.get_provider(row["providerConfigId"])
            raise ProviderNotFound(f"{agent_id}/{access_mode or '*'}")
        for row in providers:
            probe = row.get("lastProbe") or {}
            if probe.get("status") == "ready":
                return row
        # Try probing enabled ones lazily.
        for row in providers:
            probe = self.probe_provider(row["providerConfigId"])
            if probe.get("status") == "ready":
                return self.get_provider(row["providerConfigId"])
        raise ProviderNotFound("no ready provider")

    def map_external_run(self, mapping: dict[str, Any]) -> dict[str, Any]:
        required = ("executionId", "providerConfigId", "status")
        for key in required:
            if not mapping.get(key):
                raise ValueError(f"{key} required")
        return self.store.upsert_run(mapping)

    def get_external_run(self, execution_id: str) -> dict[str, Any] | None:
        return self.store.get_run(execution_id)

    def list_external_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_runs(limit=limit)

    def provider_start(self, *, provider_config_id: str, task: dict[str, Any]) -> dict[str, Any]:
        row = self.get_provider(provider_config_id)
        if not row.get("enabled"):
            return {"status": "rejected", "error": {"code": "disabled", "message": "provider disabled"}}
        adapter = get_adapter(
            row["providerLocalId"],
            binary_path=row.get("binaryPath"),
            settings=row.get("settings") or {},
        )
        result = adapter.start(task)
        if result.get("status") == "started" and result.get("externalRunRef"):
            self._run_adapters[task["executionId"]] = adapter
            self.map_external_run(
                {
                    "executionId": task["executionId"],
                    "providerConfigId": provider_config_id,
                    "externalSessionRef": result.get("externalSessionRef"),
                    "externalRunRef": result.get("externalRunRef"),
                    "adapterVersion": adapter.adapter_version,
                    "policyDigest": task.get("policyDigest"),
                    "workspaceRef": task.get("workspaceLeaseRef") or task.get("workspacePath"),
                    "status": "running",
                }
            )
        return {**result, "adapterVersion": adapter.adapter_version}

    def provider_observe(self, execution_id: str) -> list[dict[str, Any]]:
        mapping = self.get_external_run(execution_id)
        if mapping is None or not mapping.get("externalRunRef"):
            raise ProviderNotFound(execution_id)
        adapter = self._run_adapters.get(execution_id)
        if adapter is None:
            return [{"type": "terminal", "status": "outcome_unknown", "error": {"code": "run_not_attached"}}]
        events = list(adapter.observe(mapping["externalRunRef"]))
        terminal = next((e for e in reversed(events) if e.get("type") == "terminal"), None)
        if terminal and terminal.get("status") in {"succeeded", "failed", "cancelled", "outcome_unknown"}:
            self.map_external_run({**mapping, "status": terminal["status"]})
        return events

    def provider_cancel(self, execution_id: str) -> dict[str, Any]:
        mapping = self.get_external_run(execution_id)
        if mapping is None or not mapping.get("externalRunRef"):
            return {"status": "unknown"}
        adapter = self._run_adapters.get(execution_id)
        if adapter is None:
            return {"status": "unsupported", "reason": "run_not_attached"}
        result = adapter.request_cancel(mapping["externalRunRef"])
        if result.get("status") == "acknowledged":
            self.map_external_run({**mapping, "status": "cancel_requested"})
        return result
