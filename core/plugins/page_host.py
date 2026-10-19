"""Host for restricted plugin pages: Bridge identity + domain invoke."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.plugins.bridge import BridgeRegistry
from core.plugins.pages import resolve_page_html

_BILLS_METHODS = frozenset({
    "list_ledger", "list_ledger_between", "get_ledger",
    "create_ledger", "update_ledger", "delete_ledger",
    "list_statements", "get_statement",
})


class PluginPageHost:
    """Open page channels and route authorized Bridge invokes to owners."""

    def __init__(self, bridges: BridgeRegistry | None = None):
        self.bridges = bridges or BridgeRegistry()

    def open_page(
        self,
        *,
        plugin_id: str,
        page_id: str,
        user_id: str,
        instance_id: str,
        generation: int,
        package_root: Path | None = None,
    ) -> dict[str, Any]:
        root = package_root or self._package_root(plugin_id)
        resource = resolve_page_html(root, page_id)
        channel = self.bridges.open(
            plugin_id=plugin_id,
            user_id=user_id,
            instance_id=instance_id,
            generation=generation,
            page_id=page_id,
        )
        return {
            "pluginId": plugin_id,
            "pageId": page_id,
            "channelNonce": channel.channel_nonce,
            "generation": generation,
            "resourcePath": str(resource),
            "userId": user_id,
            "instanceId": instance_id,
        }

    def invoke(
        self,
        *,
        channel_nonce: str,
        plugin_id: str,
        page_id: str,
        generation: int,
        method: str,
        input: dict[str, Any] | None = None,
    ) -> Any:
        self.bridges.authorize_invoke(
            channel_nonce,
            plugin_id=plugin_id,
            generation=generation,
            page_id=page_id,
        )
        if plugin_id == "stella.bills":
            return self._invoke_bills(method, input or {})
        raise PermissionError(f"bridge invoke not enabled for {plugin_id}")

    def _invoke_bills(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _BILLS_METHODS:
            raise PermissionError(f"method not allowed on bills page: {method}")
        from application import Application
        from common.runtime_identity import RuntimeIdentity, use_identity

        port = Application.port("bills")
        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            if method == "create_ledger":
                return port.create_ledger(params)
            if method == "update_ledger":
                return port.update_ledger(params["id"], params.get("patch") or params)
            if method == "delete_ledger":
                port.delete_ledger(params["id"])
                return None
            if method == "list_ledger":
                return port.list_ledger(int(params["year"]), int(params["month"]))
            if method == "list_ledger_between":
                return port.list_ledger_between(params["start"], params["end"])
            if method == "get_ledger":
                return port.get_ledger(params["id"])
            if method == "list_statements":
                return port.list_statements(params.get("period_type"), params.get("year"))
            if method == "get_statement":
                return port.get_statement(params["id"])
        raise PermissionError(method)

    @staticmethod
    def _package_root(plugin_id: str) -> Path:
        from core.plugins.roots import resolve_plugin_package_root

        folder = plugin_id.split(".")[-1]
        env = f"STELLA_{folder.upper()}_PLUGIN_ROOT"
        if plugin_id == "stella.bills":
            env = "STELLA_BILLS_PLUGIN_ROOT"
            folder = "bills"
        return resolve_plugin_package_root(plugin_id=plugin_id, env_var=env, folder_name=folder)
