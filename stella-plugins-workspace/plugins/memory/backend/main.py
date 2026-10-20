"""Long-term memory domain. Conversation history remains owned by Core."""
from dataclasses import asdict
from pathlib import Path
import asyncio
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
_READS = ('list_files', 'get_content', 'read', 'search', 'get_context', 'get_status', 'snapshot_status')
_WRITES = ('begin_snapshot', 'restore_snapshot', 'write', 'dispatch', 'sync', 'flush_memory', 'write_daily_summary', 'deep_dream')
_MODEL_EMBED = {'search', 'sync'}
_MODEL_CHAT = {'flush_memory', 'deep_dream'}
# Per-worker summary state contains no credentials or database handles. Keep
# deduplication across RPCs while closing each invocation's SQLite connection.
_FLUSH_STATE = None
SERVICE_DESCRIPTORS = [{'contract': 'stella.memory@1', 'methods': [
    {'name': name, 'inputSchema': {'type': 'object'}, 'outputSchema': {'type': 'object'},
     'effect': 'query' if name in _READS else 'domainWrite',
     'permissions': ['memory.read' if name in _READS else 'memory.write'] +
          (['models.embedding'] if name in _MODEL_EMBED else []) + (['models.chat'] if name in _MODEL_CHAT else []),
     'resourceScope': ['user'], 'idempotency': name not in _READS, 'timeoutMs': 30000}
    for name in (*_READS, *_WRITES)]}]


class HostModel:
    def call(self, request):
        from stella_host import invoke
        result = invoke('stella.models@1', 'complete', {'request': request})
        if result['status'] != 'succeeded':
            raise RuntimeError('model service unavailable')
        return result['value']['response']


def _handle(params):
    global _FLUSH_STATE
    from memory_domain.config import MemoryConfig
    from memory_domain.manager import MemoryManager
    from memory_domain.service import MemoryService
    from memory_domain.embedding.host import create_default_embedding_provider
    handle = params.get('_hostDataHandle') or {}
    if handle.get('namespace') != 'stella.memory' or not handle.get('dataDir'):
        raise PermissionError('bound memory namespace required')
    root = Path(handle['dataDir']).resolve()
    values = dict(params.get('input') or {})
    method = params['method']
    if method == 'search':
        for key in ('max_results', 'min_score'):
            if key not in values and key in handle.get('settings', {}):
                values[key] = handle['settings'][key]
    manager = None
    try:
        service = MemoryService(str(root))
        if method in {'list_files', 'get_content', 'dispatch'}:
            value = getattr(service, method)(**values)
        elif method in {'begin_snapshot', 'restore_snapshot', 'snapshot_status'}:
            from memory_domain import snapshots
            action = {'begin_snapshot': snapshots.begin, 'restore_snapshot': snapshots.restore, 'snapshot_status': snapshots.status}[method]
            value = action(root, **values)
        elif method == 'write':
            from memory_domain.documents import write
            value = write(root, **values)
        elif method in {'read', 'get_context'}:
            relative = values.get('path', 'MEMORY.md')
            if not isinstance(relative, str) or relative.startswith(('/', '\\')) or '..' in relative.replace('\\','/').split('/'):
                raise ValueError('invalid memory path')
            if relative != 'MEMORY.md' and not relative.startswith('memory/'):
                raise ValueError('only memory documents may be read')
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or path.suffix != '.md':
                raise PermissionError('memory path escapes namespace')
            content = path.read_text(encoding='utf-8') if path.is_file() else ''
            start = max(1, int(values.get('start_line', 1)))
            count = values.get('num_lines')
            lines = content.splitlines()
            selected = lines[start-1:start-1+int(count)] if count is not None else lines[start-1:]
            value = {'path': relative, 'content': '\n'.join(selected), 'total_lines': len(lines)}
            if method == 'get_context':
                from memory_domain.prompt import context_prompt
                value['prompt'] = context_prompt(values.get('language'), content)
        else:
            embedding = create_default_embedding_provider() if method in _MODEL_EMBED else None
            manager = MemoryManager(MemoryConfig(workspace_root=str(root)), embedding_provider=embedding, llm_model=HostModel())
            if _FLUSH_STATE is not None and _FLUSH_STATE[0] == root:
                manager.flush_manager = _FLUSH_STATE[1]
            else:
                _FLUSH_STATE = (root, manager.flush_manager)
            if embedding:
                manager.config.embedding_provider = embedding.provider
                manager.config.embedding_model = embedding.model
                manager.config.embedding_dim = embedding.dimensions
            if method == 'search':
                asyncio.run(manager.sync())
                value = {'results': [asdict(item) for item in asyncio.run(manager.search(**values))]}
            elif method == 'sync':
                asyncio.run(manager.sync(**values))
                value = manager.get_status()
            elif method == 'get_status':
                value = manager.get_status()
            elif method == 'flush_memory':
                summaries = []
                value = {'flushed': manager.flush_memory(**values, context_summary_callback=summaries.append)}
                value['summary'] = summaries[0] if summaries else ''
            elif method == 'write_daily_summary':
                value = {'written': manager.flush_manager.write_daily_summary(**values)}
            elif method == 'deep_dream':
                allowed = values.get('force', False) or handle.get('settings', {}).get('deep_dream_enabled', True)
                value = {'dreamed': manager.flush_manager.deep_dream(**values) if allowed else False}
            else:
                raise ValueError('unknown memory method')
        return {'status': 'succeeded', 'sideEffects': 'none' if method in _READS else 'committed', 'value': value}
    except (ValueError, FileNotFoundError, PermissionError, KeyError) as exc:
        return {'status': 'failed', 'sideEffects': 'none', 'error': {'code': 'invalid_argument', 'message': str(exc)}}
    finally:
        if manager:
            manager.close()


def handle_invoke(params):
    if params["method"] in _WRITES:
        from stella_host import mutate
        return mutate(params, _handle)
    return _handle(params)
