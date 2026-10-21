"""Owner-backed references, distinct from collected records and model context."""
from dataclasses import asdict, dataclass

from core.data.store import stable_id

COLLECTION_OPERATIONS = frozenset({'metadata', 'configure', 'resources', 'read', 'sync', 'subscribe', 'deliver', 'delete', 'export'})
REFERENCE_OPERATIONS = frozenset({'metadata', 'configure', 'resources', 'read'})


@dataclass(frozen=True)
class Resource:
    id: str
    source_id: str
    provider: str
    reference: str
    kind: str
    name: str
    operations: tuple[str, ...] = ('read',)

    @classmethod
    def from_source(cls, source, reference, *, kind, name, operations=('read',)):
        return cls(stable_id(source['provider'], source['id'], reference), source['id'],
                   source['provider'], reference, kind, name, tuple(operations))

    def as_dict(self):
        return {**asdict(self), 'operations': list(self.operations)}


def validate_resource(value, source):
    if isinstance(value, dict):
        try:
            value = Resource(**{**value, 'operations': tuple(value.get('operations', ('read',)))})
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid resource metadata') from exc
    if not isinstance(value, Resource) or any(not isinstance(field, str) or not field or len(field) > 8192
            for field in (value.id, value.source_id, value.provider, value.reference, value.kind, value.name)):
        raise ValueError('Invalid resource metadata')
    if (value.source_id != source['id'] or value.provider != source['provider']
            or value.id != stable_id(source['provider'], source['id'], value.reference)):
        raise ValueError('Resource identity does not belong to its source')
    if not isinstance(value.operations, tuple) or set(value.operations) - {'read'}:
        raise ValueError('Unsupported resource operations')
    return value
