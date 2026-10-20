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
_EMAIL_METHODS = frozenset({"list_accounts", "get_account", "list_folders", "test_connection"})
_ELEARNING_METHODS = frozenset({"list_courses", "get_settings", "test_connection"})
_AUTOMATION_METHODS = frozenset({"list_tasks", "get_task", "enable_task"})
_AGENT_HUB_METHODS = frozenset({
    "list_catalog", "status_overview", "list_providers", "get_provider",
    "probe_provider", "ensure_defaults", "upsert_provider", "delete_provider",
    "list_external_runs", "get_external_run",
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
        if plugin_id == "stella.email":
            return self._invoke_email(method, params)
        if plugin_id == "stella.elearning":
            return self._invoke_elearning(method, params)
        if plugin_id == "stella.automation":
            return self._invoke_automation(method, params)
        if plugin_id == "stella.agent-hub":
            return self._invoke_agent_hub(method, params)
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

    def _invoke_email(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _EMAIL_METHODS:
            raise PermissionError(f"method not allowed on email page: {method}")
        from application import Application
        from common.runtime_identity import RuntimeIdentity, use_identity

        port = Application.port("email")
        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            if method == "list_accounts":
                return port.list_accounts()
            if method == "get_account":
                return port.get_account(params["account_id"])
            if method == "list_folders":
                return port.list_folders(params.get("account_id"))
            if method == "test_connection":
                return port.test_connection(params)
        raise PermissionError(method)

    def _invoke_elearning(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _ELEARNING_METHODS:
            raise PermissionError(f"method not allowed on elearning page: {method}")
        from application import Application
        from common.runtime_identity import RuntimeIdentity, use_identity

        port = Application.port("elearning")
        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            if method == "list_courses":
                return port.list_courses()
            if method == "get_settings":
                return port.get_settings()
            if method == "test_connection":
                return port.test_connection(params)
        raise PermissionError(method)

    def _invoke_automation(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _AUTOMATION_METHODS:
            raise PermissionError(f"method not allowed on automation page: {method}")
        from common.runtime_identity import RuntimeIdentity, use_identity
        from common.state_dir import scheduler_file
        from core.services import automation_gateway

        db_path = Path(scheduler_file()).with_name("automation.db")
        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            result = automation_gateway.invoke_automation(
                method, params, db_path=db_path, agent_id="plugin-ui",
            )
        status = result.get("status")
        if status == "failed":
            raise ValueError((result.get("error") or {}).get("message") or "automation call failed")
        if status != "succeeded":
            raise RuntimeError(f"automation plugin returned {status}")
        return result.get("value")

    def _invoke_agent_hub(self, method: str, params: dict[str, Any]) -> Any:
        if method not in _AGENT_HUB_METHODS:
            raise PermissionError(f"method not allowed on agent-hub page: {method}")
        from common.runtime_identity import RuntimeIdentity, use_identity
        from core.services import agent_hub_gateway

        with use_identity(RuntimeIdentity(agent_id="plugin-ui", user_id="desktop")):
            result = agent_hub_gateway.invoke_agent_hub(
                method, params, agent_id="plugin-ui",
            )
        status = result.get("status")
        if status == "failed":
            raise ValueError((result.get("error") or {}).get("message") or "agent-hub call failed")
        if status != "succeeded":
            raise RuntimeError(f"agent-hub plugin returned {status}")
        return result.get("value")

    @staticmethod
    def _package_root(plugin_id: str) -> Path:
        from core.plugins.roots import resolve_plugin_package_root

        folder = plugin_id.split(".")[-1]
        env = f"STELLA_{folder.upper()}_PLUGIN_ROOT"
        aliases = {
            "stella.bills": ("STELLA_BILLS_PLUGIN_ROOT", "bills"),
            "stella.tasks": ("STELLA_TASKS_PLUGIN_ROOT", "tasks"),
            "stella.calendar": ("STELLA_CALENDAR_PLUGIN_ROOT", "calendar"),
            "stella.briefing": ("STELLA_BRIEFING_PLUGIN_ROOT", "briefing"),
            "stella.email": ("STELLA_EMAIL_PLUGIN_ROOT", "email"),
            "stella.elearning": ("STELLA_ELEARNING_PLUGIN_ROOT", "elearning"),
            "stella.automation": ("STELLA_AUTOMATION_PLUGIN_ROOT", "automation"),
            "stella.agent-hub": ("STELLA_AGENT_HUB_PLUGIN_ROOT", "agent-hub"),
        }
        if plugin_id in aliases:
            env, folder = aliases[plugin_id]
        return resolve_plugin_package_root(plugin_id=plugin_id, env_var=env, folder_name=folder)
