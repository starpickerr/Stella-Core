"""Feature-to-source selections. These preferences never grant data access."""
from dataclasses import dataclass
from threading import RLock
from typing import Callable


@dataclass(frozen=True)
class DataConsumer:
    id: str
    name: dict
    providers: frozenset[str]
    default_enabled: bool = False
    available: Callable[[], bool] | None = None


class ConsumerRegistry:
    """Host registration only; plugin callbacks cannot create functional consumers."""
    def __init__(self):
        self._items: dict[str, DataConsumer] = {}
        self._lock = RLock()

    def register(self, consumer):
        if not isinstance(consumer, DataConsumer) or not consumer.id or not consumer.providers:
            raise ValueError('Invalid data consumer')
        with self._lock:
            if consumer.id in self._items:
                raise ValueError('Data consumer is already registered')
            self._items[consumer.id] = consumer

    def get(self, consumer_id):
        with self._lock:
            if consumer_id not in self._items:
                raise ValueError('Data consumer is not registered')
            return self._items[consumer_id]

    def items(self):
        with self._lock:
            return list(self._items.values())


def _briefing_available():
    from core.services.briefing_gateway import briefing_plugin_enabled
    return briefing_plugin_enabled()


DEFAULT_CONSUMERS = ConsumerRegistry()
DEFAULT_CONSUMERS.register(DataConsumer('stella.briefing', {'zh': '简报', 'en': 'Briefing'},
    frozenset({'email', 'elearning'}), default_enabled=True, available=_briefing_available))


class UsageService:
    def __init__(self, service):
        self.service = service

    def _consumer_source(self, consumer_id, source_id):
        self.service._identity()
        consumer = DEFAULT_CONSUMERS.get(consumer_id)
        source = self.service.store.source(source_id)
        if source['provider'] not in consumer.providers:
            raise ValueError('Source is not supported by this data consumer')
        return consumer, source

    def binding(self, consumer_id, source_id):
        consumer, source = self._consumer_source(consumer_id, source_id)
        with self.service.store.connection() as db:
            row = db.execute('SELECT enabled,selected,revision FROM source_usage WHERE consumer=? AND source_id=?',
                             (consumer_id, source_id)).fetchone()
        default = source.get('default_usage', {}).get(consumer_id, consumer.default_enabled)
        return {'consumer_id': consumer_id, 'source_id': source_id,
                'enabled': bool(row['enabled']) if row else bool(default),
                'selected': bool(row['selected']) if row else bool(default),
                'revision': row['revision'] if row else 0}

    def enabled(self, consumer_id, source_id):
        row = self.binding(consumer_id, source_id)
        return row['selected'] and row['enabled']

    def set(self, consumer_id, source_id, enabled, selected=True):
        if type(enabled) is not bool or type(selected) is not bool or (enabled and not selected):
            raise ValueError('Usage selection must use boolean states')
        self._consumer_source(consumer_id, source_id)
        source = self.service._guard(source_id, 'configure', allow_disabled=True)
        prepare = getattr(self.service.providers.get(source['provider']), 'prepare_usage', None)
        if enabled and callable(prepare):
            previous = self.binding(consumer_id, source_id)
            # Freeze the legacy default before activating an owner. If the
            # remote step fails or final commit fails, discovery cannot turn
            # that partial preparation into an enabled consumer relationship.
            with self.service.store.connection() as db:
                db.execute('INSERT OR IGNORE INTO source_usage(consumer,source_id,enabled,selected) VALUES(?,?,?,?)',
                           (consumer_id, source_id, int(previous['enabled']), int(previous['selected'])))
            prepare(source, consumer_id)
            self.service._guard(source_id, 'configure', allow_disabled=True)
        with self.service.store.connection() as db:
            db.execute('INSERT INTO source_usage(consumer,source_id,enabled,selected,revision) VALUES(?,?,?,?,1) '
                       'ON CONFLICT(consumer,source_id) DO UPDATE SET '
                       'revision=revision+CASE WHEN enabled=excluded.enabled AND selected=excluded.selected THEN 0 ELSE 1 END, '
                       'enabled=excluded.enabled,selected=excluded.selected',
                       (consumer_id, source_id, int(enabled), int(selected)))
        return self.binding(consumer_id, source_id)

    def snapshot(self):
        sources = self.service.list_sources()
        consumers, usages = [], []
        for consumer in DEFAULT_CONSUMERS.items():
            available = consumer.available() if callable(consumer.available) else True
            consumers.append({'id': consumer.id, 'name': consumer.name, 'available': bool(available)})
            usages.extend(self.binding(consumer.id, source['id']) for source in sources
                          if source['provider'] in consumer.providers)
        return {'usage_consumers': consumers, 'usages': usages}


def enforce_selection(service, source):
    from core.plugins.caller import current_consumer_plugin
    consumer_id = current_consumer_plugin()
    if not consumer_id:
        return
    try:
        consumer = DEFAULT_CONSUMERS.get(consumer_id)
    except ValueError:
        return  # Existing undeclared consumers retain their existing Grant behavior.
    if source['provider'] in consumer.providers:
        binding = UsageService(service).binding(consumer_id, source['id'])
        if not binding['selected'] or not binding['enabled']:
            raise PermissionError('Data source usage is disabled for this consumer')
        return binding['revision']
