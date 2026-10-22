"""Resource type filtering precedes pagination for the global data catalog."""
import pytest

from core.data.resources import Resource
from core.data.service import DataService, ProviderRegistry
from tests.test_data_resources import ReferenceProvider


def test_resource_type_filter_precedes_pagination_and_rechecks_owner(tmp_path):
    class Owner(ReferenceProvider):
        def resources(self, source, query, limit, offset):
            rows = [Resource.from_source(source, str(index), name=str(index),
                    kind='assignment' if index % 2 else 'announcement') for index in range(245)]
            return {'resources': rows[offset:offset + limit], 'total': len(rows)}
    registry = ProviderRegistry()
    registry.register('documents', Owner())
    service = DataService(tmp_path / 'data.db', registry)
    service.discover()
    page = service.resources('documents:library', kind='assignment', offset=100, limit=50)
    assert page['total'] == 122 and len(page['resources']) == 22
    assert all(row['kind'] == 'assignment' for row in page['resources'])
    assert page['resources'][0]['reference'] == '201'
    with pytest.raises(ValueError):
        service.resources('documents:library', kind=['assignment'])
