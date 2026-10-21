"""Native product adapter; source and record rules live in DataService."""

from core.data.runtime import current_service
from core.data import storage
from agent.permission.data_access import authorize
from contextlib import nullcontext
from dataclasses import dataclass
from core.plugins.caller import consumer_plugin_scope


@dataclass(frozen=True)
class Consumer:
    handler: object
    plugin_id: str | None = None


def consume_briefing(event):
    if event.get("record") is not None:
        from core.services.briefing_facade import BriefingPluginFacade

        BriefingPluginFacade().upsert_source_item(event["record"])


class DataController:
    def __init__(self, service=None, *, consumers=None):
        self.service = service if service is not None else current_service()
        self.consumers = (
            {"briefing": Consumer(consume_briefing, "stella.briefing")}
            if consumers is None
            else consumers
        )

    def snapshot(self, refresh=False):
        authorize("metadata", "Data Service")
        discovered = (
            self.service.discover()
            if refresh or not self.service.list_sources()
            else {"errors": []}
        )
        sources = []
        for source in self.service.list_sources():
            provider = self.service.providers.get(source["provider"])
            state = self.service.sync_state(source["id"])
            sources.append(
                {
                    key: source.get(key)
                    for key in [
                        "id",
                        "name",
                        "kind",
                        "account_id",
                        "provider",
                        "enabled",
                        "storage",
                        "retention_days",
                    ]
                }
            )
            sources[-1].update(
                {
                    key: source[key]
                    for key in ["connection", "settings_url"]
                    if key in source
                }
            )
            sources[-1].update(
                {key: state[key] for key in ["running", "last_run", "error"]}
            )
            sources[-1]["operations"] = sorted(self.service._operations(source))
            sources[-1]["representation"] = "collection" if callable(getattr(provider, "fetch", None)) else "reference"
            sources[-1]['resource_kinds'] = source.get('resource_kinds', [source['kind']])
            sources[-1]["available"] = (
                source["present"] and getattr(provider, "available", lambda: True)()
            )
        subscriptions = self.service.subscriptions()
        deliveries = []
        for subscription in subscriptions:
            deliveries.extend(self.service.deliveries(subscription["id"]))
        with self.service.store.connection() as db:
            count = db.execute(
                "SELECT count(*) FROM records WHERE deleted=0"
            ).fetchone()[0]
        return {
            "sources": sources,
            "providers": self.service.providers.descriptors(),
            "record_count": count,
            "subscriptions": subscriptions,
            "deliveries": deliveries,
            "consumers": [
                {"id": name, "name": "简报" if name == "briefing" else name}
                for name in self.consumers
            ],
            "storage": storage.inventory(),
            "errors": discovered["errors"],
        }

    def records(self, source_id, query="", limit=50, offset=0):
        return self.service.query(source_id, query, limit, offset)

    def resources(self, source_id, query='', limit=50, offset=0, *, kind=None):
        return self.service.resources(source_id, query, limit, offset, kind=kind)

    def read_resource(self, source_id, resource_id):
        return self.service.read_resource(source_id, resource_id)

    def owner_operation(self, provider_id, operation, values):
        sources = self.service.discover()['sources']
        active = [source for source in sources if source['provider'] == provider_id and source['present']]
        if len(active) != 1:
            raise PermissionError('Source owner is unavailable or ambiguous')
        return self.service.owner_operation(active[0]['id'], operation, values)

    def command(self, body):
        if not isinstance(body, dict):
            raise ValueError("Data command must be an object")
        action = body.get("action")
        allowed = {
            "discover": set(),
            "source": {"source_id", "enabled", "storage", "retention_days"},
            "sync": {"source_id", "options"},
            "subscribe": {"source_id", "consumer_id", "filter", "include_existing"},
            "subscription": {"subscription_id", "enabled"},
            "dispatch": {"subscription_id"},
            "delete_record": {"record_id"},
            "cleanup": {"source_id", "all_records"},
            "export": {"source_id"},
            "cleanup_storage": {"cleanup_action"},
        }
        if (
            not isinstance(action, str)
            or action not in allowed
            or set(body) - ({"action"} | allowed[action])
        ):
            raise ValueError("Unknown data command or parameters")

        def required(key):
            value = body.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(key + " is required")
            return value

        if action == "discover":
            return self.service.discover()
        if action == "source":
            return {
                "source": self.service.configure_source(
                    required("source_id"),
                    **{
                        key: value
                        for key, value in body.items()
                        if key not in {"action", "source_id"}
                    },
                )
            }
        if action == "sync":
            result = self.service.sync(required("source_id"), body.get("options", {}))
            return {
                "sync": {
                    "processed": len(result["records"]),
                    "errors": result["errors"],
                }
            }
        if action == "subscribe":
            consumer = required("consumer_id")
            if consumer not in self.consumers:
                raise ValueError("Data consumer is not registered")
            return {
                "subscription": self.service.subscribe(
                    required("source_id"),
                    consumer,
                    body.get("filter"),
                    include_existing=body.get("include_existing", False),
                )
            }
        if action == "subscription":
            return {
                "subscription": self.service.set_subscription_enabled(
                    required("subscription_id"), body.get("enabled")
                )
            }
        if action == "dispatch":
            row = self.service._subscription(required("subscription_id"))
            consumer = self.consumers.get(row["consumer"])
            if consumer is None:
                raise ValueError("Data consumer is not registered")
            # Only trusted registration binds a plugin identity. A subscription
            # label is never itself a credential; existing delegation survives.
            scope = (
                consumer_plugin_scope(consumer.plugin_id)
                if isinstance(consumer, Consumer) and consumer.plugin_id
                else nullcontext()
            )
            handler = consumer.handler if isinstance(consumer, Consumer) else consumer
            with scope:
                return {"delivery": self.service.dispatch(row["id"], handler)}
        if action == "delete_record":
            return self.service.delete_record(required("record_id"))
        if action == "cleanup":
            if type(body.get("all_records", False)) is not bool:
                raise ValueError("all_records must be a boolean")
            return (
                self.service.purge(required("source_id"))
                if body.get("all_records")
                else self.service.cleanup(required("source_id"))
            )
        if action == "export":
            return {"export": self.service.export(required("source_id"))}
        return storage.cleanup(required("cleanup_action"))


def current_controller():
    return DataController()


def invoke_public(method, payload):
    """Read-only plugin contract. Identity comes from the host callback scope."""
    controller = current_controller()
    allowed = {'resources': {'source_id', 'query', 'limit', 'offset'},
               'read_resource': {'source_id', 'resource_id'}}
    if method not in allowed or not isinstance(payload, dict) or set(payload) - allowed[method]:
        raise PermissionError('Data method or parameters are not public')
    result = getattr(controller, method)(**payload)
    return {'status': 'succeeded', 'sideEffects': 'none', 'value': result}
