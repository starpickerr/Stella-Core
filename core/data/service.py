"""Reusable data collection and delivery; no consumer-specific business rules."""

import json
import re
import time
import uuid
from dataclasses import asdict

from common.runtime_identity import current_identity
from core.data.store import DataStore, encode, stable_id, matches
from core.data.resources import Resource, validate_resource, COLLECTION_OPERATIONS, REFERENCE_OPERATIONS


class ProviderRegistry:
    def __init__(self):
        self._providers = {}

    def register(self, name, provider):
        if not isinstance(name, str) or not re.fullmatch(
            r"[a-z][a-z0-9_.-]{0,79}", name
        ):
            raise ValueError("Invalid provider ID")
        if name in self._providers:
            raise ValueError("Provider already registered")
        if not all(
            callable(getattr(provider, method, None))
            for method in ["discover", "authorize"]
        ):
            raise ValueError("Provider must implement discover and authorize")
        if not callable(getattr(provider, "fetch", None)) and not all(
                callable(getattr(provider, method, None)) for method in ("resources", "read_resource")):
            raise ValueError("Provider must implement collection or owner-backed resources")
        self._providers[name] = provider

    def get(self, name):
        try:
            return self._providers[name]
        except KeyError:
            raise RuntimeError("Source provider is unavailable") from None

    def items(self):
        return self._providers.items()

    def descriptors(self):
        return [{'id': name, 'representation': 'collection' if callable(getattr(provider, 'fetch', None)) else 'reference',
                 'operations': sorted(COLLECTION_OPERATIONS if callable(getattr(provider, 'fetch', None)) else REFERENCE_OPERATIONS)}
                for name, provider in self.items()]


class DataService:
    def __init__(self, path, providers):
        self.user = current_identity().user_id or "local-default"
        self.store = DataStore(path)
        self.providers = providers

    def _identity(self):
        if (current_identity().user_id or "local-default") != self.user:
            raise PermissionError("Data service belongs to another user")
        from core.plugins.cancellation import check_cancelled
        from core.security.service import SecurityService

        check_cancelled()
        SecurityService.check_execution()

    def _operations(self, source):
        provider = self.providers.get(source['provider'])
        defaults = COLLECTION_OPERATIONS if callable(getattr(provider, 'fetch', None)) else REFERENCE_OPERATIONS
        return source.get('operations', defaults)

    def _guard(self, source_id, operation, *, allow_disabled=False):
        self._identity()
        source = self.store.source(source_id)
        if not source["enabled"] and not allow_disabled:
            raise PermissionError("Data source is disabled")
        if not source["present"] and not allow_disabled:
            raise PermissionError("Data source is unavailable")
        if operation not in self._operations(source):
            raise ValueError('Source does not support ' + operation)
        self.providers.get(source["provider"]).authorize(source, operation)
        if self.store.source(source_id)["revision"] != source["revision"]:
            raise PermissionError("Source configuration changed during authorization")
        return source

    def discover(self):
        self._identity()
        errors = []
        for provider_id, provider in self.providers.items():
            try:
                specs = provider.discover()
            except (PermissionError, RuntimeError, OSError) as error:
                errors.append({"provider": provider_id, "message": str(error)[:500]})
                continue
            if not isinstance(specs, list):
                raise ValueError("Provider returned invalid source list")
            for spec in specs:
                if (
                    not isinstance(spec, dict)
                    or not all(
                        isinstance(spec.get(key), str) and spec[key]
                        for key in ["id", "name", "kind"]
                    )
                    or not isinstance(spec.get("config", {}), dict)
                ):
                    raise ValueError("Provider returned invalid source metadata")
                if 'account_id' in spec and not isinstance(spec['account_id'], str):
                    raise ValueError('Invalid source account metadata')
                if callable(getattr(provider, 'fetch', None)) and not spec.get('account_id'):
                    raise ValueError('Collecting sources require an account')
                operations = spec.get('operations')
                if operations is not None and (not isinstance(operations, list) or not all(
                        isinstance(op, str) and op in COLLECTION_OPERATIONS for op in operations)):
                    raise ValueError('Invalid source operations')
                if not callable(getattr(provider, 'fetch', None)) and operations is not None and set(operations) - REFERENCE_OPERATIONS:
                    raise ValueError('Reference provider does not support collection operations')
            if len({spec['id'] for spec in specs}) != len(specs):
                raise ValueError('Duplicate source identity')
            partition = getattr(provider, 'discovery_partition', lambda: None)()
            if partition is not None and (not isinstance(partition, str) or not partition
                    or any(spec.get('discovery_partition') != partition for spec in specs)):
                raise ValueError('Invalid provider discovery partition')
            self.store.discover_batch(provider_id, specs, partition)
        return {"sources": self.list_sources(), "errors": errors}

    def list_sources(self):
        self._identity()
        rows = []
        for source in self.store.sources():
            try:
                provider = self.providers.get(source['provider'])
                visible = getattr(provider, 'visible', lambda source: True)
                if visible(source):
                    rows.append(source)
            except (PermissionError, RuntimeError):
                continue
        return rows

    def configure_source(self, source_id, **values):
        self._guard(source_id, "configure", allow_disabled=True)
        source = self.store.source(source_id)
        if not callable(getattr(self.providers.get(source['provider']), 'fetch', None)) and set(values) - {'enabled'}:
            raise ValueError('Reference source does not support collection storage settings')
        if not values or set(values) - {"enabled", "storage", "retention_days"}:
            raise ValueError("Unsupported source setting")
        if "enabled" in values and type(values["enabled"]) is not bool:
            raise ValueError("enabled must be a boolean")
        if "storage" in values and values["storage"] not in {
            "reference",
            "cache",
            "persistent",
        }:
            raise ValueError("Invalid storage policy")
        if "retention_days" in values and (
            type(values["retention_days"]) is not int
            or not 1 <= values["retention_days"] <= 3650
        ):
            raise ValueError("Invalid retention period")
        return self.store.configure(source_id, values)

    def sync_state(self, source_id):
        self._guard(source_id, "metadata", allow_disabled=True)
        return self.store.state(source_id)

    def sync(self, source_id, options=None):
        source = self._guard(source_id, "sync")
        if options is not None and not isinstance(options, dict):
            raise ValueError("Sync options must be an object")
        token, cursors, revision = self.store.claim_sync(source_id)
        try:
            source = self._guard(source_id, "sync")
            if source["revision"] != revision:
                raise PermissionError("Source configuration changed before collection")
            result = self.providers.get(source["provider"]).fetch(
                source, cursors, options or {}
            )
            self._guard(source_id, "sync")
            items = []
            for item in result.items:
                value = asdict(item)
                if (
                    value["account_id"] != source["account_id"]
                    or not value["source_id"]
                ):
                    raise PermissionError("Record is outside the bound source account")
                items.append(value)
            if not isinstance(result.cursors, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in result.cursors.items()
            ):
                raise ValueError("Provider returned invalid sync cursors")
            records = self.store.commit_batch(
                source_id,
                token,
                revision,
                items,
                cursors if result.errors else result.cursors,
                lambda: self._guard(source_id, "sync"),
            )
            self.store.finish_sync(source_id, token, "; ".join(result.errors))
            return {
                "records": records,
                "cursors": cursors if result.errors else result.cursors,
                "errors": list(result.errors),
            }
        except BaseException as error:
            self.store.finish_sync(
                source_id, token, type(error).__name__ + ": " + str(error)[:500]
            )
            raise

    @staticmethod
    def _visible(source, row):
        return not row["deleted"] and (
            source["storage"] != "cache"
            or row["updated_at"] >= time.time() - source["retention_days"] * 86400
        )

    def query(self, source_id, query="", limit=50, offset=0):
        source = self._guard(source_id, "read")
        if (
            not isinstance(query, str)
            or len(query) > 1000
            or type(limit) is not int
            or not 1 <= limit <= 200
            or type(offset) is not int
            or offset < 0
        ):
            raise ValueError("Invalid data query or pagination")
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT * FROM records WHERE source_id=? AND deleted=0 ORDER BY updated_at DESC,id",
                (source_id,),
            ).fetchall()
            values = []
            for row in rows:
                item = json.loads(row["content"])
                if (
                    self._visible(source, row)
                    and query.casefold()
                    in (item["title"] + " " + item["snippet"]).casefold()
                ):
                    values.append(
                        {
                            "id": row["id"],
                            "source_id": source_id,
                            "item": item,
                            "version": row["digest"],
                        }
                    )
        if self._guard(source_id, "read")["revision"] != source["revision"]:
            raise PermissionError("Source configuration changed during query")
        return {
            "records": values[offset : offset + limit],
            "total": len(values),
            "offset": offset,
            "limit": limit,
        }

    @staticmethod
    def _pagination(query, limit, offset):
        if (not isinstance(query, str) or len(query) > 1000 or type(limit) is not int
                or not 1 <= limit <= 200 or type(offset) is not int or offset < 0):
            raise ValueError('Invalid resource query or pagination')

    def resources(self, source_id, query='', limit=50, offset=0):
        self._pagination(query, limit, offset)
        source = self._guard(source_id, 'resources')
        provider = self.providers.get(source['provider'])
        if callable(getattr(provider, 'resources', None)):
            page = provider.resources(source, query, limit, offset)
            if (not isinstance(page, dict) or not isinstance(page.get('resources'), list)
                    or type(page.get('total')) is not int or page['total'] < 0
                    or len(page['resources']) > limit):
                raise ValueError('Invalid resource page')
            resources = [validate_resource(item, source) for item in page['resources']]
        else:
            page = self.query(source_id, query, limit, offset)
            resources = [Resource.from_source(source, row['id'], kind=source['kind'],
                         name=row['item']['title'] or row['item']['source_id']) for row in page['records']]
        if len({resource.id for resource in resources}) != len(resources):
            raise ValueError('Duplicate resource identity')
        if self._guard(source_id, 'resources')['revision'] != source['revision']:
            raise PermissionError('Source configuration changed during resource discovery')
        self.store.put_resources(source, resources)
        return {'resources': [resource.as_dict() for resource in resources],
                'total': page['total'], 'offset': offset, 'limit': limit}

    def read_resource(self, source_id, resource_id):
        source = self._guard(source_id, 'read')
        resource = validate_resource(self.store.resource(source_id, resource_id), source)
        if 'read' not in resource.operations:
            raise ValueError('Resource does not support read')
        provider = self.providers.get(source['provider'])
        authorize_resource = getattr(provider, 'authorize_resource', lambda *_: None)
        authorize_resource(source, resource, 'read')
        if callable(getattr(provider, 'read_resource', None)):
            result = provider.read_resource(source, resource)
            if not isinstance(result, dict) or set(result) != {'resource', 'content'}:
                raise ValueError('Invalid resource read result')
            returned = validate_resource(result['resource'], source)
            if returned.id != resource.id:
                raise ValueError('Resource identity changed during read')
            content = result['content']
        else:
            row = self.store.record(resource.reference)
            if row['source_id'] != source_id or not self._visible(source, row):
                raise PermissionError('Resource is no longer available')
            returned, content = resource, json.loads(row['content'])
        if self._guard(source_id, 'read')['revision'] != source['revision']:
            raise PermissionError('Source configuration changed during resource read')
        authorize_resource(source, resource, 'read')
        self._identity()
        return {'resource': returned.as_dict(), 'content': content}

    def events(self, source_id, limit=100):
        self._guard(source_id, "read")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid event limit")
        with self.store.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM events WHERE source_id=? ORDER BY seq DESC LIMIT ?",
                    (source_id, limit),
                )
            ][::-1]

    def delete_record(self, record_id):
        self._identity()
        row = self.store.record(record_id)
        self._guard(row["source_id"], "delete", allow_disabled=True)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._guard(row["source_id"], "delete", allow_disabled=True)
            current = db.execute(
                "SELECT * FROM records WHERE id=?", (record_id,)
            ).fetchone()
            removed = self.store.tombstone(db, current)
        return {"removed": int(removed)}

    def cleanup(self, source_id):
        source = self._guard(source_id, "delete", allow_disabled=True)
        if source["storage"] != "cache":
            return {"removed": 0}
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._guard(source_id, "delete", allow_disabled=True)
            rows = db.execute(
                "SELECT * FROM records WHERE source_id=? AND deleted=0 AND updated_at<?",
                (source_id, time.time() - source["retention_days"] * 86400),
            ).fetchall()
            for row in rows:
                self.store.tombstone(db, row)
        return {"removed": len(rows)}

    def purge(self, source_id):
        self._guard(source_id, "delete", allow_disabled=True)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._guard(source_id, "delete", allow_disabled=True)
            rows = db.execute(
                "SELECT * FROM records WHERE source_id=? AND deleted=0", (source_id,)
            ).fetchall()
            for row in rows:
                self.store.tombstone(db, row)
        return {"removed": len(rows)}

    def export(self, source_id):
        source = self._guard(source_id, "export")
        records = []
        offset = 0
        while True:
            page = self.query(source_id, limit=200, offset=offset)
            records.extend(page["records"])
            offset += len(page["records"])
            if not page["records"] or offset >= page["total"]:
                break
        if self._guard(source_id, "export")["revision"] != source["revision"]:
            raise PermissionError("Source configuration changed during export")
        return {"format": "stella-data-v1", "source_id": source_id, "records": records}

    def subscribe(self, source_id, consumer_id, filter=None, *, include_existing=False):
        self._guard(source_id, "subscribe")
        if (
            not isinstance(consumer_id, str)
            or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.:-]{0,119}", consumer_id)
            or type(include_existing) is not bool
        ):
            raise ValueError("Invalid consumer ID or replay option")
        filter = {} if filter is None else filter
        if (
            not isinstance(filter, dict)
            or set(filter) - {"q", "event_types"}
            or not isinstance(filter.get("q", ""), str)
            or len(filter.get("q", "")) > 1000
            or not isinstance(filter.get("event_types", []), list)
            or any(
                value not in {"created", "updated", "deleted"}
                for value in filter.get("event_types", [])
            )
        ):
            raise ValueError("Invalid subscription filter")
        identifier = stable_id(source_id, consumer_id, filter)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO subscriptions(id,source_id,consumer,filter) VALUES(?,?,?,?)",
                (identifier, source_id, consumer_id, encode(filter)),
            )
            if include_existing:
                for event in db.execute(
                    "SELECT * FROM events e WHERE source_id=? AND seq=(SELECT max(seq) FROM events newer WHERE newer.record_id=e.record_id) ORDER BY seq",
                    (source_id,),
                ).fetchall():
                    row = db.execute(
                        "SELECT content FROM records WHERE id=?", (event["record_id"],)
                    ).fetchone()
                    if row and matches(
                        filter, json.loads(row["content"]), event["type"]
                    ):
                        db.execute(
                            "INSERT OR IGNORE INTO deliveries(subscription_id,event_id) VALUES(?,?)",
                            (identifier, event["id"]),
                        )
        return {
            "id": identifier,
            "source_id": source_id,
            "consumer": consumer_id,
            "filter": filter,
            "enabled": bool(self._subscription(identifier)["enabled"]),
        }

    def subscriptions(self):
        self._identity()
        with self.store.connection() as db:
            return [
                {
                    **dict(row),
                    "filter": json.loads(row["filter"]),
                    "enabled": bool(row["enabled"]),
                }
                for row in db.execute("SELECT * FROM subscriptions ORDER BY id")
            ]

    def _subscription(self, identifier):
        self._identity()
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM subscriptions WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise KeyError("Subscription not found")
        return dict(row)

    def set_subscription_enabled(self, identifier, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        row = self._subscription(identifier)
        self._guard(row["source_id"], "subscribe", allow_disabled=True)
        with self.store.connection() as db:
            db.execute(
                "UPDATE subscriptions SET enabled=? WHERE id=?", (enabled, identifier)
            )
        return {"id": identifier, "enabled": enabled}

    def deliveries(self, subscription_id):
        subscription = self._subscription(subscription_id)
        self._guard(subscription["source_id"], "metadata", allow_disabled=True)
        with self.store.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT d.*,e.type,e.record_id,e.seq FROM deliveries d JOIN events e ON e.id=d.event_id WHERE subscription_id=? ORDER BY e.seq",
                    (subscription_id,),
                )
            ]

    def dispatch(self, subscription_id, handler, *, limit=50):
        subscription = self._subscription(subscription_id)
        if not subscription["enabled"]:
            raise PermissionError("Subscription is disabled")
        self._guard(subscription["source_id"], "deliver")
        if not callable(handler) or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid consumer handler or limit")
        delivered = failed = 0
        for _ in range(limit):
            self._guard(subscription["source_id"], "deliver")
            token = uuid.uuid4().hex
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT enabled FROM subscriptions WHERE id=?", (subscription_id,)
                ).fetchone()
                if not current["enabled"]:
                    break
                event = db.execute(
                    """SELECT e.*,d.state,d.lease_until FROM deliveries d JOIN events e ON e.id=d.event_id
                    WHERE d.subscription_id=? AND d.state!='delivered' ORDER BY e.seq LIMIT 1""",
                    (subscription_id,),
                ).fetchone()
                if event is None or (
                    event["state"] == "delivering"
                    and event["lease_until"] >= time.time()
                ):
                    break
                db.execute(
                    "UPDATE deliveries SET state='delivering',attempts=attempts+1,lease=?,lease_until=? WHERE subscription_id=? AND event_id=?",
                    (token, time.time() + 120, subscription_id, event["id"]),
                )
            try:
                source = self._guard(subscription["source_id"], "deliver")
                record = self.store.record(event["record_id"])
                if (
                    self._guard(subscription["source_id"], "deliver")["revision"]
                    != source["revision"]
                ):
                    raise PermissionError(
                        "Source configuration changed during delivery"
                    )
                if not self._subscription(subscription_id)["enabled"]:
                    raise PermissionError("Subscription is disabled")
                item = json.loads(record["content"])
                value = {
                    **dict(event),
                    "content_semantics": "current-state",
                    "record": item
                    if event["type"] != "deleted" and self._visible(source, record)
                    else None,
                    "record_version": record["digest"],
                }
                # Events are durable change notifications, not retained body
                # snapshots. Recheck content filters against the authorized
                # current state. Deleted notifications never carry new bodies.
                if event["type"] == "deleted" or (
                    value["record"] is not None
                    and matches(json.loads(subscription["filter"]), item, event["type"])
                ):
                    handler(value)
                with self.store.connection() as db:
                    count = db.execute(
                        "UPDATE deliveries SET state='delivered',lease=NULL,lease_until=0,error='',delivered_at=? WHERE subscription_id=? AND event_id=? AND lease=?",
                        (time.time(), subscription_id, event["id"], token),
                    ).rowcount
                delivered += count
            except Exception as error:
                with self.store.connection() as db:
                    db.execute(
                        "UPDATE deliveries SET state='failed',lease=NULL,lease_until=0,error=? WHERE subscription_id=? AND event_id=? AND lease=?",
                        (
                            type(error).__name__ + ": " + str(error)[:500],
                            subscription_id,
                            event["id"],
                            token,
                        ),
                    )
                if isinstance(error, PermissionError):
                    raise
                failed += 1
                break  # A failed head cannot be overtaken or retried in a tight loop.
        return {"delivered": delivered, "failed": failed}
