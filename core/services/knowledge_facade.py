"""Host adapter for the public Knowledge plugin contract; no domain implementation."""
import base64
from core.services.knowledge_gateway import invoke_knowledge

MAX_IMPORT_FILES = 100
MAX_IMPORT_FILE_SIZE = 10 * 1024 * 1024
MAX_IMPORT_TOTAL_SIZE = 200 * 1024 * 1024


def call(method, **params):
    from common.state_dir import knowledge_dir
    result = invoke_knowledge(method, params, data_dir=knowledge_dir(ensure=False))
    if result['status'] != 'succeeded':
        error = result.get('error') or {}
        raise ValueError(error.get('message') or 'knowledge plugin unavailable')
    return result.get('value')


class KnowledgePort:
    def __init__(self, workspace_root=None):
        # Identity is resolved by Core; callers cannot select another user's path.
        pass

    @property
    def knowledge_dir(self):
        from common.state_dir import knowledge_dir
        return str(knowledge_dir(ensure=False))

    def list_tree(self):
        return call('list_tree')

    def read_file(self, path):
        return call('read_file', path=path)

    def build_graph(self):
        return call('build_graph')

    def dispatch(self, action, payload):
        payload = dict(payload)
        if action == 'import_documents':
            payload['files'] = [{**{key: value for key, value in row.items() if key != 'content'},
                'contentBase64': base64.b64encode(row.get('content', b'')).decode('ascii')}
                for row in payload.get('files') or []]
        return call('dispatch', action=action, payload=payload)
