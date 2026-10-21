"""Resource references resolved by existing first-party plugin contracts.

Only directory metadata enters Data Service. Business reads, authorization and
storage remain with the domain's existing managed worker and grants.
"""
import importlib
import json

from core.data.resources import Resource, REFERENCE_OPERATIONS
from core.plugins.caller import (gateway_invocation_scope, managed_data_lease,
                                 plugin_user_id, user_grant_ref)
from core.plugins.lifecycle import domain_data_handle


OWNERS = {
    'tasks': ('todos', 'list_todos', {'include_completed': True}, 'get_todo', 'todo_id', 'title', '/todos'),
    'calendar': ('calendar', 'list_events', {}, 'get_event', 'id', 'title', '/calendar'),
    'bills': ('bills', 'list_ledger_between', {'start': '0001-01-01', 'end': '9999-12-31'},
              'get_ledger', 'id', 'name', '/bills'),
    'briefing': ('briefing', 'list_briefings', {}, 'get_briefing', 'briefing_id', 'date', '/briefing'),
    'knowledge': ('knowledge', 'list_tree', {}, 'read_file', 'path', 'title', '/knowledge'),
    'memory': ('memory', 'list_files', {'page': 1, 'page_size': 200}, 'get_content', 'filename', 'filename', '/memory'),
}


class PluginResourceProvider:
    def __init__(self, owner):
        if owner not in OWNERS:
            raise ValueError('Unknown resource owner')
        self.owner = owner
        self.domain, self.list_method, self.list_args, self.read_method, self.read_key, self.name_key, self.url = OWNERS[owner]
        self.plugin_id = 'stella.' + owner

    @property
    def gateway(self):
        return importlib.import_module('core.services.' + self.domain + '_gateway')

    def available(self):
        if not getattr(self.gateway, self.domain + '_plugin_enabled')():
            return False
        try:
            with managed_data_lease(self.plugin_id):
                return True
        except PermissionError:
            return False

    def discover(self):
        if not self.available():
            return []
        return [{'id': 'plugin:' + self.plugin_id + ':' + plugin_user_id(),
                 'kind': self.owner, 'name': self.owner.title(),
                 'config': {'owner': self.plugin_id}, 'connection': 'plugin:' + self.plugin_id,
                 'settings_url': self.url, 'operations': sorted(REFERENCE_OPERATIONS)}]

    def _invoke(self, method, values, *, check_only=False):
        if not self.available():
            raise PermissionError('Resource owner is not enabled')
        gateway = self.gateway
        with gateway_invocation_scope(gateway.__name__):
            session = getattr(gateway, 'ensure_' + self.domain + '_session')()
            result = session.invoke_contract(contract=self.plugin_id + '@1', method=method,
                input_payload=values, origin='system', grant_ref=user_grant_ref(gateway._GRANT_REF),
                data_handle=domain_data_handle(self.plugin_id, plugin_user_id()), check_only=check_only)
            if result['status'] != 'succeeded':
                raise RuntimeError((result.get('error') or {}).get('message', 'Resource owner read failed'))
            return result.get('value')

    def authorize(self, source, operation):
        from agent.permission.data_access import authorize
        if (source['id'] != 'plugin:' + self.plugin_id + ':' + plugin_user_id()
                or source['config'] != {'owner': self.plugin_id}):
            raise PermissionError('Resource source belongs to another owner')
        if operation in {'metadata', 'configure'}:
            authorize(operation, source['id'])
        elif not self.available():
            raise PermissionError('Resource owner is not enabled')
        elif operation == 'resources':
            self._invoke(self.list_method, dict(self.list_args), check_only=True)

    def _rows(self):
        value = self._invoke(self.list_method, dict(self.list_args))
        if self.owner == 'knowledge':
            def walk(files, nodes, prefix=''):
                for row in files:
                    yield prefix + row['name'], row.get('title') or row['name']
                for node in nodes:
                    yield from walk(node['files'], node['children'], prefix + node['dir'] + '/')
            yield from walk(value.get('root_files', []), value['tree'])
        elif self.owner == 'memory':
            for category in ('memory', 'evolution'):
                page = 1
                current = value if category == 'memory' else None
                while True:
                    current = current or self._invoke(self.list_method, {'page': page, 'page_size': 200, 'category': category})
                    for row in current['list']:
                        kind = row['type'] if row['type'] in {'dream', 'evolution'} else 'memory'
                        yield json.dumps([kind, row['filename']], ensure_ascii=False), row['filename']
                    if page * 200 >= current['total']:
                        break
                    if not current['list']:
                        raise RuntimeError('Resource owner returned incomplete pagination')
                    page += 1
                    current = None
        else:
            for row in value:
                yield str(row['id']), str(row.get(self.name_key) or row['id'])

    def resources(self, source, query, limit, offset):
        rows = [Resource.from_source(source, reference, kind=self.owner, name=name)
                for reference, name in self._rows() if query.casefold() in name.casefold()]
        return {'resources': rows[offset:offset + limit], 'total': len(rows)}

    def _read_args(self, resource):
        if self.owner == 'memory':
            category, filename = json.loads(resource.reference)
            return {'category': category, 'filename': filename}
        return {self.read_key: resource.reference}

    def authorize_resource(self, source, resource, operation):
        self._invoke(self.read_method, self._read_args(resource), check_only=True)

    def read_resource(self, source, resource):
        value = self._invoke(self.read_method, self._read_args(resource))
        if value is None:
            raise FileNotFoundError('Resource no longer exists')
        return {'resource': resource, 'content': value}
