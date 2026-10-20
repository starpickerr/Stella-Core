"""Knowledge domain worker. Its data directory never grants access to memory."""
from pathlib import Path
import asyncio
import base64
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

_READS = ('list_tree', 'read_file', 'build_graph', 'search', 'get_context')
SERVICE_DESCRIPTORS = [{'contract': 'stella.knowledge@1', 'methods': [
    {'name': method, 'inputSchema': {'type': 'object'}, 'outputSchema': {'type': 'object'},
     'effect': 'query' if method in _READS else 'domainWrite',
     'permissions': ['knowledge.read' if method in _READS else 'knowledge.write'] + (['models.embedding'] if method == 'search' else []),
     'resourceScope': ['user'], 'idempotency': method not in _READS, 'timeoutMs': 30000}
    for method in (*_READS, 'dispatch')]}]


def _handle(params):
    from knowledge_domain.service import KnowledgeService
    handle = params.get('_hostDataHandle') or {}
    if handle.get('namespace') != 'stella.knowledge' or not handle.get('dataDir'):
        raise PermissionError('bound knowledge data required')
    service = KnowledgeService(handle['dataDir'])
    values = dict(params.get('input') or {})
    method = params['method']
    if method == 'search':
        for key in ('max_results', 'min_score'):
            if key not in values and key in handle.get('settings', {}):
                values[key] = handle['settings'][key]
    try:
        if method == 'list_tree':
            value = service.list_tree()
        elif method == 'read_file':
            value = service.read_file(values['path'])
            value['dir'] = str((Path(service.knowledge_dir) / value['path']).parent)
        elif method == 'build_graph':
            value = service.build_graph()
        elif method == 'search':
            value = {'results': asyncio.run(service._manager().search(**values))}
        elif method == 'get_context':
            try:
                value = service.read_file('index.md')
            except FileNotFoundError:
                value = {'content': ''}
            from knowledge_domain.prompt import context_prompt
            value['prompt'] = context_prompt(values.get('language'), value['content'])
        elif method == 'dispatch':
            payload = dict(values.get('payload') or {})
            if values.get('action') == 'import_documents':
                payload['files'] = [{**row, 'content': base64.b64decode(row['contentBase64'], validate=True)}
                                    for row in payload.get('files') or []]
            value = service.dispatch(values['action'], payload)
        else:
            raise ValueError('unknown knowledge method')
        return {'status': 'succeeded', 'sideEffects': 'committed' if method == 'dispatch' else 'none', 'value': value}
    except (ValueError, KeyError, FileNotFoundError, PermissionError) as exc:
        return {'status': 'failed', 'sideEffects': 'none', 'error': {'code': 'invalid_argument', 'message': str(exc)}}


def handle_invoke(params):
    if params["method"] == "dispatch":
        from stella_host import mutate
        return mutate(params, _handle)
    return _handle(params)
