"""References to authorized workspace files; contents remain with Workspace Service."""
import os
from pathlib import Path

from common.runtime_identity import current_identity
from core.data.resources import Resource
from core.data.store import stable_id
from core.security.service import SecurityService
from core.workspace.service import WorkspaceService, SEARCH_SKIP_DIRS, MAX_SEARCH_WALK


class WorkspaceProvider:
    def _context(self):
        return WorkspaceService.context()

    def _scope(self):
        context = self._context()
        identity = current_identity()
        return {'root': str(context.root), 'agent': context.agent_id,
                'session': identity.execution_session_id or identity.session_id, 'task': identity.task_id}

    def discovery_partition(self):
        scope = self._scope()
        return stable_id(scope['agent'], scope['session'], scope['task'])

    def discover(self):
        scope = self._scope()
        # A background host with no conversation/task does not implicitly
        # register the parent containing all private conversation folders.
        if not scope['session'] and not scope['task']:
            return []
        return [{'id': 'workspace:' + stable_id(scope), 'name': Path(scope['root']).name,
                 'kind': 'workspace', 'config': scope, 'discovery_partition': self.discovery_partition(),
                 'resource_kinds': ['file'],
                 'operations': ['metadata', 'configure', 'resources', 'read']}]

    def visible(self, source):
        return source.get('config') == self._scope()

    def authorize(self, source, operation):
        if not self.visible(source):
            raise PermissionError('Workspace source belongs to another execution context')
        SecurityService.check_execution()
        if operation == 'configure':
            from agent.permission.data_access import authorize
            authorize(operation, source['id'])

    def _allowed(self, path):
        from agent.tools.utils.credentials import is_credential_path
        from agent.workspace.context import private_access
        if is_credential_path(str(path)) or private_access(str(path), self._context()) == 'deny':
            return False
        return SecurityService.authorize_tool('read', {'path': str(path)}, noninteractive=True) is None

    def resources(self, source, query, limit, offset):
        self.authorize(source, 'resources')
        context = self._context()
        service = WorkspaceService(str(context.root))
        rows = []
        walked = 0
        for parent, dirs, files in os.walk(context.root, followlinks=False):
            dirs[:] = sorted(name for name in dirs if name not in SEARCH_SKIP_DIRS and not name.startswith('.')
                             and not (Path(parent) / name).is_symlink() and self._allowed(Path(parent) / name))
            for name in sorted(files):
                walked += 1
                if walked > MAX_SEARCH_WALK:
                    raise ValueError('Workspace resource scan is too large; choose a smaller project')
                path = Path(parent) / name
                if name.startswith('.') or path.is_symlink() or not self._allowed(path):
                    continue
                relative = service.to_rel(str(path))
                if query.casefold() not in relative.casefold():
                    continue
                rows.append(Resource.from_source(source, relative, kind='file', name=relative))
        return {'resources': rows[offset:offset + limit], 'total': len(rows)}

    def read_resource(self, source, resource):
        self.authorize(source, 'read')
        service = WorkspaceService(str(self._context().root))
        path = service.resolve(resource.reference)
        if not self._allowed(path):
            raise PermissionError('Workspace resource access denied')
        result = service.read_text(resource.reference)
        if result['truncated']:
            raise ValueError('Resource exceeds text read limit; use the workspace file viewer')
        if not self._allowed(path):
            raise PermissionError('Workspace resource access revoked')
        return {'resource': resource, 'content': result['content']}
