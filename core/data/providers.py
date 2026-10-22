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
    "cursor_argument": "cursors",
    "errors": "errors",
    "boolean_options": ["refresh_existing_content"],
}


def field(value, path, default=None):
    if path is None:
        return default
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


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
        if self.mapping.get("discovery_rows"):
            rows = field(rows, self.mapping["discovery_rows"])
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
        cursor_argument = self.mapping.get("cursor_argument")
        cursor_key = self.mapping.get("cursor_key")
        if cursor_argument:
            if cursor_key:
                if cursor_key in cursors:
                    values[cursor_argument] = cursors[cursor_key]
            else:
                values[cursor_argument] = dict(cursors)
        for option, argument in self.mapping["options"].items():
            if option in options and options[option] is not None:
                value = options[option]
                if option in self.mapping.get("boolean_options", []) and isinstance(
                    value, str
                ):
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
        rows = field(result, self.mapping["items"])
        if not isinstance(rows, list):
            raise ValueError("MCP provider returned an invalid record list")
        items = []
        for row in rows:
            if self.mapping.get("record_fields"):
                values = {
                    "source": self.mapping["kind"],
                    "account_id": source["account_id"],
                }
                for target, path in self.mapping["record_fields"].items():
                    value = field(row, path)
                    if value is None:
                        continue
                    if target.startswith("payload."):
                        values.setdefault("payload", {})[
                            target.removeprefix("payload.")
                        ] = value
                    else:
                        values[target] = value
            else:
                values = row
            items.append(FetchedItem(**values))
        next_cursor = field(result, self.mapping.get("cursors"), {})
        if cursor_key:
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise ValueError("Mapped MCP cursor must be a string")
            next_cursor = {cursor_key: next_cursor} if next_cursor is not None else {}
        return FetchResult(
            items,
            next_cursor,
            field(result, self.mapping.get("errors"), []),
        )


class DataSource:
    """A consumer uses this Source protocol, without knowing the MCP mapping."""

    def __init__(self, service, source, consumer_id=None):
        self.consumer_id = consumer_id
        self.service = service
        self.source_id = source["id"]
        self.name = source["kind"]
        self.account_id = source["account_id"]
        self.display_name = source["name"]
        self.cancel_event = None

    def fetch(self, cursors):
        from core.plugins.cancellation import cancellation_scope

        from contextlib import nullcontext
        from core.plugins.caller import consumer_plugin_scope
        consumer = consumer_plugin_scope(self.consumer_id) if self.consumer_id else nullcontext()
        with consumer, cancellation_scope(self.cancel_event):
            source = self.service._guard(self.source_id, 'read')
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
            self.service._recheck(source, 'read')
            return FetchResult(items, outcome["cursors"], outcome["errors"])
