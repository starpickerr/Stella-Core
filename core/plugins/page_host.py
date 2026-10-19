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
_TASKS_METHODS = frozenset({
    "list_todos", "list_todos_focus", "get_todo",
    "create_todo", "update_todo", "complete_todo", "delete_todo",
})
_CALENDAR_METHODS = frozenset({
    "list_events", "get_event", "create_event", "update_event", "delete_event",
})
_BRIEFING_METHODS = frozenset({
    "list_briefings", "get_briefing", "get_preferences", "update_preferences",
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
        params = input or {}
        if plugin_id == "stella.bills":
            return self._invoke_bills(method, params)
        if plugin_id == "stella.tasks":
            return self._invoke_tasks(method, params)
        if plugin_id == "stella.calendar":
            return self._invoke_calendar(method, params)
        if plugin_id == "stella.briefing":
            return self._invoke_briefing(method, params)
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

    def _invoke_tasks(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _TASKS_METHODS:
            raise PermissionError(f"method not allowed on tasks page: {method}")
        from application import Application
        from common.runtime_identity import RuntimeIdentity, use_identity

        port = Application.port("todos")
        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            if method == "create_todo":
                return port.create_todo(params.get("payload") or params)
            if method == "update_todo":
                return port.update_todo(params["todo_id"], params.get("payload") or {})
            if method == "complete_todo":
                return port.complete_todo(
                    params["todo_id"], bool(params.get("completed", True)),
                    bool(params.get("force", False)),
                )
            if method == "delete_todo":
                port.delete_todo(params["todo_id"], bool(params.get("preserve_children", False)))
                return None
            if method == "get_todo":
                return port.get_todo(params["todo_id"])
            if method == "list_todos":
                return port.list_todos(
                    params.get("start"), params.get("end"),
                    bool(params.get("include_completed", False)),
                )
            if method == "list_todos_focus":
                return port.list_todos_focus(params.get("today"))
        raise PermissionError(method)

    def _invoke_calendar(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _CALENDAR_METHODS:
            raise PermissionError(f"method not allowed on calendar page: {method}")
        from application import Application
        from common.runtime_identity import RuntimeIdentity, use_identity

        port = Application.port("calendar")
        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            if method == "create_event":
                return port.create_event(params.get("payload") or params)
            if method == "update_event":
                return port.update_event(params["id"], params.get("payload") or params.get("patch") or {})
            if method == "delete_event":
                port.delete_event(params["id"])
                return None
            if method == "get_event":
                return port.get_event(params["id"])
            if method == "list_events":
                return port.list_events(params.get("start"), params.get("end"), params.get("category_id"))
        raise PermissionError(method)

    def _invoke_briefing(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _BRIEFING_METHODS:
            raise PermissionError(f"method not allowed on briefing page: {method}")
        from application import Application
        from common.runtime_identity import RuntimeIdentity, use_identity

        port = Application.port("briefing")
        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            if method == "list_briefings":
                return port.list_briefings(params.get("status"))
            if method == "get_briefing":
                return port.get_briefing(params["briefing_id"])
            if method == "get_preferences":
                return port.get_preferences()
            if method == "update_preferences":
                return port.update_preferences(params.get("payload") or params)
        raise PermissionError(method)

    @staticmethod
    def _package_root(plugin_id: str) -> Path:
        from core.plugins.roots import resolve_plugin_package_root

        folder = plugin_id.split(".")[-1]
        env = f"STELLA_{folder.upper()}_PLUGIN_ROOT"
        if plugin_id == "stella.bills":
            env = "STELLA_BILLS_PLUGIN_ROOT"
            folder = "bills"
        elif plugin_id == "stella.tasks":
            env = "STELLA_TASKS_PLUGIN_ROOT"
            folder = "tasks"
        elif plugin_id == "stella.calendar":
            env = "STELLA_CALENDAR_PLUGIN_ROOT"
            folder = "calendar"
        elif plugin_id == "stella.briefing":
            env = "STELLA_BRIEFING_PLUGIN_ROOT"
            folder = "briefing"
        return resolve_plugin_package_root(plugin_id=plugin_id, env_var=env, folder_name=folder)
