"""Trusted default local Server registrations and backward-compatible intent."""

import os
from pathlib import Path
import sys
import shutil

LOCAL_READS = frozenset(
    {"list_accounts", "list_sources", "get_account", "get_settings", "get_cursors"}
)

PUBLIC_TOOLS = {
    "elearning": ["list_courses", "fetch", "list_files", "sync_files"],
    "email": ["list_accounts", "list_sources", "fetch_messages"],
}


def configurations(manager):
    if os.environ.get("STELLA_MANAGED_MCP", "1") == "0":
        return []
    from common.runtime_identity import use_identity
    from core.plugins.management import default_store

    with use_identity(manager.identity):
        store = default_store()
        user = manager.identity.user_id or "local-default"
        configs = []
        for domain in PUBLIC_TOOLS:
            repo_name = "fudan-elearning-mcp" if domain == "elearning" else "email-mcp"
            repo = Path(
                os.environ.get(
                    f"STELLA_{domain.upper()}_MCP_ROOT",
                    str(Path(__file__).resolve().parents[3] / "MCP" / repo_name),
                )
            ).resolve()
            if getattr(sys, "frozen", False):
                binary = (
                    Path(sys.executable).resolve().parent.parent
                    / (domain + "-mcp")
                    / (domain + "-mcp" + (".exe" if os.name == "nt" else ""))
                )
                command = str(binary)
                launch = []
            elif (repo / "mcp_server.py").is_file():
                python = (
                    repo
                    / ".venv"
                    / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                )
                command = str(python) if python.is_file() else sys.executable
                launch = [str(repo / "mcp_server.py")]
            else:
                command = shutil.which(domain + "-mcp") or domain + "-mcp"
                launch = []
            from importlib import import_module

            paths = import_module("core.services." + domain + "_facade")._paths()
            data = paths[0].parent if domain == "email" else paths[0]
            legacy = paths[1].parent if domain == "email" else paths[1]
            enabled = store.instance("stella." + domain, user)["intent"] == "enabled"
            if os.environ.get(f"STELLA_{domain.upper()}_PLUGIN", "").lower() in {
                "0",
                "false",
                "no",
            }:
                enabled = False
            if domain == "elearning":
                enabled = enabled and manager.capability_settings.enabled(
                    "tool", "elearning"
                )
            configs.append(
                {
                    "name": domain,
                    "type": "stdio",
                    "command": command,
                    "args": launch
                    + [
                        "--data-dir",
                        str(data),
                        "--legacy-dir",
                        str(legacy),
                        "--user-id",
                        user,
                    ],
                    "env": {
                        key: os.environ.get(key, "")
                        if user == "local-default" and domain == "email"
                        else ""
                        for key in [
                            "IMAP_HOST",
                            "IMAP_USER",
                            "IMAP_PASSWORD",
                            "IMAP_PORT",
                            "IMAP_FOLDER",
                            "CANVAS_TOKEN",
                        ]
                    },
                    "enabled": enabled,
                    "timeout": 600,
                    "agentTools": PUBLIC_TOOLS[domain],
                    "settingsUrl": "/" + domain,
                }
            )
        return configs


def enabled(domain):
    from agent.tools.tool_manager import ToolManager

    manager = ToolManager()
    config = next((c for c in manager._load_mcp_configs() if c["name"] == domain), None)
    return bool(config and manager._mcp_enabled(config))


def invoke(domain, method, params, *, purpose=None):
    from agent.tools.tool_manager import ToolManager
    from core.plugins.cancellation import current_cancellation_events

    events = current_cancellation_events()

    class Cancellation:
        def is_set(self):
            return any(event.is_set() for event in events)

    result = ToolManager().call_mcp_tool(
        domain,
        method,
        params,
        host=True,
        purpose=purpose,
        cancel_event=Cancellation() if events else None,
    )
    return {"status": "succeeded", "value": result}


def native_user_action(host, method, purpose):
    from core.execution.context import current_execution_context
    active = current_execution_context()
    if active:
        active.check_active()
        if active.origin != 'ui' or active.purpose == 'background':
            return False
    from core.plugins.caller import (
        current_caller_origin,
        current_delegation,
        current_consumer_plugin,
        current_invocation_purpose,
    )

    return (
        host
        and purpose != "background"
        and current_invocation_purpose() != "background"
        and method not in {"fetch", "fetch_source", "fetch_messages", "sync_files"}
        and current_caller_origin() in {None, "ui", "system"}
        and not current_delegation()
        and not current_consumer_plugin()
    )
