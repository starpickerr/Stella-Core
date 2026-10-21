"""Provider-side mappings and one source adapter shared by data consumers."""

from datetime import datetime

from core.data.store import stable_id
from core.services.source_types import FetchedItem, FetchResult

# Mapping describes a general IMAP source. It has no briefing-specific API.
EMAIL_MAPPING = {
    "discover": "list_sources",
    "kind": "email",
    "account_field": "account_id",
    "name_field": "name",
    "source_args": {"account_id": "mailbox_id"},
    "fetch": "fetch_messages",
    "options": {
        "since": "since",
        "until": "until",
        "refresh_existing_content": "refresh_existing_content",
        "lookback_days": "lookback_days",
    },
    "items": "items",
    "cursors": "cursors",
    "errors": "errors",
}


class McpProvider:
    def __init__(self, server, mapping, manager=None):
        self.server = server
        self.mapping = mapping
        self._manager = manager

    @property
    def manager(self):
        if self._manager is None:
            from agent.tools.tool_manager import ToolManager

            return ToolManager()
        return self._manager

    def available(self):
        return any(
            config.get("name") == self.server and self.manager._mcp_enabled(config)
            for config in self.manager._load_mcp_configs()
        )

    def discover(self):
        rows = self.manager.call_mcp_tool(self.server, self.mapping["discover"], {})
        if not isinstance(rows, list):
            raise ValueError("MCP source discovery returned an invalid list")
        result = []
        for row in rows:
            account = row[self.mapping["account_field"]]
            args = {
                param: row[field]
                for param, field in self.mapping["source_args"].items()
            }
            if (
                not isinstance(account, str)
                or not account
                or any(
                    not isinstance(value, str) or not value for value in args.values()
                )
            ):
                raise ValueError("MCP source identity is invalid")
            result.append(
                {
                    "id": "mcp:" + self.server + ":" + stable_id(account),
                    "name": row[self.mapping["name_field"]],
                    "kind": self.mapping["kind"],
                    "account_id": account,
                    "config": args,
                    "connection": "mcp:" + self.server,
                    "settings_url": "/" + self.server,
                }
            )
        return result

    def authorize(self, source, operation):
        if operation in {"configure", "metadata", "subscribe", "delete"}:
            from agent.permission.data_access import authorize

            authorize(operation, source["id"])
            return
        # The exact same admission, disabled-tool, connection, grant, resource
        # and execution policy checks protect cached and upstream reads.
        self.manager.call_mcp_tool(
            self.server, self.mapping["fetch"], dict(source["config"]), check_only=True
        )
        if operation == "export":
            from agent.permission.data_access import authorize

            authorize(operation, source["id"])

    def fetch(self, source, cursors, options):
        values = dict(source["config"])
        values["cursors"] = dict(cursors)
        for option, argument in self.mapping["options"].items():
            if option in options and options[option] is not None:
                value = options[option]
                if option == "refresh_existing_content" and isinstance(value, str):
                    value = value in {"1", "true"}
                values[argument] = value
        from core.plugins.cancellation import current_cancellation_events

        events = current_cancellation_events()

        class Cancellation:
            def is_set(self):
                return any(event.is_set() for event in events)

        result = self.manager.call_mcp_tool(
            self.server,
            self.mapping["fetch"],
            values,
            cancel_event=Cancellation() if events else None,
        )
        return FetchResult(
            [FetchedItem(**item) for item in result[self.mapping["items"]]],
            result.get(self.mapping["cursors"], {}),
            result.get(self.mapping["errors"], []),
        )


class DataSource:
    """A consumer uses this Source protocol, without knowing the MCP mapping."""

    def __init__(self, service, source):
        self.service = service
        self.source_id = source["id"]
        self.name = source["kind"]
        self.account_id = source["account_id"]
        self.display_name = source["name"]
        self.cancel_event = None

    def fetch(self, cursors):
        from core.plugins.cancellation import cancellation_scope

        with cancellation_scope(self.cancel_event):
            outcome = self.service.sync(self.source_id, dict(cursors))
            items = []
            offset = 0
            since = cursors.get("since")
            until = cursors.get("until")
            start = (
                datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
            )
            end = (
                datetime.fromisoformat(until.replace("Z", "+00:00")) if until else None
            )
            while True:
                page = self.service.query(self.source_id, limit=200, offset=offset)
                for row in page["records"]:
                    item = FetchedItem(**row["item"])
                    stamp = (
                        datetime.fromisoformat(item.occurred_at.replace("Z", "+00:00"))
                        if item.occurred_at
                        else None
                    )
                    if (start or end) and stamp is None:
                        continue
                    if start and stamp < start or end and stamp > end:
                        continue
                    items.append(item)
                offset += len(page["records"])
                if not page["records"] or offset >= page["total"]:
                    break
            return FetchResult(items, outcome["cursors"], outcome["errors"])
