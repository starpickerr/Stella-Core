"""eLearning resource directory over the single managed MCP connection."""
import json
from datetime import datetime, timezone

from core.data.providers import McpProvider
from core.data.resources import Resource, REFERENCE_OPERATIONS
from core.data.store import stable_id


class ElearningProvider:
    def __init__(self, manager=None):
        self.connection = McpProvider('elearning', {}, manager)

    @property
    def manager(self):
        return self.connection.manager

    def available(self):
        return self.connection.available()

    def _call(self, method, values, *, check_only=False):
        from core.plugins.cancellation import current_cancellation_events
        events = current_cancellation_events()

        class Cancellation:
            def is_set(self):
                return any(event.is_set() for event in events)

        return self.manager.call_mcp_tool('elearning', method, values,
            host=method == 'get_settings', check_only=check_only,
            cancel_event=Cancellation() if events else None)

    def discover(self):
        if not self.available():
            return []
        settings = self._call('get_settings', {})
        if not settings.get('configured'):
            return []
        account = settings['account_id']
        return [{'id': 'mcp:elearning:' + stable_id(account), 'name': 'eLearning',
                 'kind': 'elearning', 'config': {'account_id': account},
                 'resource_kinds': ['course', 'announcement', 'assignment', 'quiz', 'grade', 'file'],
                 'connection': 'mcp:elearning', 'settings_url': '/elearning',
                 'operations': sorted(REFERENCE_OPERATIONS)}]

    def authorize(self, source, operation):
        if operation in {'metadata', 'configure'}:
            from agent.permission.data_access import authorize
            authorize(operation, source['id'])
            return
        settings = self._call('get_settings', {})
        if not settings.get('configured') or settings['account_id'] != source['config']['account_id']:
            raise PermissionError('eLearning source account changed')
        if operation == 'resources':
            self._call('list_courses', {}, check_only=True)

    @staticmethod
    def _fetch_args(course):
        # The resource browser includes history and upcoming course work. It
        # does not advance the background consumer's independent sync cursors.
        return {'course_ids': [course], 'since': '1970-01-01T00:00:00Z',
                'until': datetime.now(timezone.utc).isoformat(), 'limit': 50}

    def _pages(self, method, values, key):
        offset = 0
        while True:
            page = self._call(method, {**values, 'offset': offset})
            if page.get('errors'):
                raise RuntimeError('eLearning resource query incomplete: ' + '; '.join(page['errors']))
            yield from page[key]
            next_offset = page.get('next_offset')
            if next_offset is None:
                return
            if type(next_offset) is not int or next_offset <= offset:
                raise ValueError('Invalid eLearning resource pagination')
            offset = next_offset

    @staticmethod
    def _resource(source, kind, course, reference, name):
        return Resource.from_source(source, json.dumps([kind, course, reference], ensure_ascii=False),
                                    kind=kind, name=name)

    def resources(self, source, query, limit, offset):
        resources = []
        courses = self._call('list_courses', {})
        readable = False
        for course in courses:
            course_id = course['id']
            try:
                self._call('fetch', self._fetch_args(course_id), check_only=True)
            except PermissionError:
                pass
            else:
                readable = True
                resources.append(self._resource(source, 'course', course_id, course_id, course['name']))
                for row in self._pages('fetch', self._fetch_args(course_id), 'source_items'):
                    kind = row['payload']['resource_type']
                    if kind != 'file':
                        resources.append(self._resource(source, kind, course_id, row['source_id'], row['title']))
            try:
                self._call('list_files', {'course_ids': [course_id]}, check_only=True)
            except PermissionError:
                pass
            else:
                readable = True
                for row in self._pages('list_files', {'course_ids': [course_id], 'limit': 200}, 'files'):
                    resources.append(self._resource(source, 'file', course_id, row['file_id'], row['filename']))
        if courses and not readable:
            raise PermissionError('No authorized eLearning course resources')
        for resource in resources:
            self.authorize_resource(source, resource, 'read')
        filtered = [row for row in resources if query.casefold() in row.name.casefold()]
        return {'resources': filtered[offset:offset + limit], 'total': len(filtered)}

    def authorize_resource(self, source, resource, operation):
        kind, course, reference = json.loads(resource.reference)
        if kind == 'file':
            self._call('list_files', {'course_ids': [course], 'file_ids': [reference]}, check_only=True)
        else:
            self._call('fetch', self._fetch_args(course), check_only=True)
            if kind == 'course':
                self._call('list_courses', {}, check_only=True)

    def read_resource(self, source, resource):
        kind, course, reference = json.loads(resource.reference)
        if kind == 'course':
            rows = (row for row in self._call('list_courses', {}) if row['id'] == course)
        elif kind == 'file':
            rows = self._pages('list_files', {'course_ids': [course], 'file_ids': [reference], 'limit': 200}, 'files')
        else:
            rows = (row for row in self._pages('fetch', self._fetch_args(course), 'source_items')
                    if row['source_id'] == reference and row['payload']['resource_type'] == kind)
        value = next(rows, None)
        if value is None:
            raise FileNotFoundError('eLearning resource no longer exists')
        return {'resource': resource, 'content': value}
