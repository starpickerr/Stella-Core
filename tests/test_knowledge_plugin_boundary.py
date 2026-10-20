"""Knowledge runs in a worker and owns an index independent of long-term memory."""
from pathlib import Path

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.host import PluginSession
from core.plugins.registry import PluginRegistry

ROOT = Path(__file__).resolve().parents[2] / 'Stella-Plugins/plugins/knowledge'


def test_knowledge_worker_owns_documents_and_searches_only_knowledge(tmp_path):
    knowledge = tmp_path / 'knowledge'
    (knowledge / 'notes').mkdir(parents=True)
    (knowledge / 'notes/page.md').write_text('# Notes\n独立知识检索 boundarytoken', encoding='utf-8')
    (tmp_path / 'MEMORY.md').write_text('privatetoken', encoding='utf-8')
    session = PluginSession(ROOT, source_label='test', registry=PluginRegistry(),
                            user_id='test-user', authz=PluginAuthorizationStore())
    try:
        session.start()
        def invoke(method, **values):
            result = session.invoke(method, {**values, '_dataHandle': {
                'namespace': 'stella.knowledge', 'dataDir': str(knowledge)}})
            assert result['status'] == 'succeeded', result
            return result['value']
        assert invoke('list_tree')['stats']['pages'] == 1
        assert 'boundarytoken' in invoke('read_file', path='notes/page.md')['content']
        assert invoke('search', query='boundarytoken')['results']
        assert invoke('search', query='privatetoken')['results'] == []
        prompt = invoke('get_context', language='en')['prompt']
        assert 'sources/' in prompt and 'create_document' in prompt
        denied = session.invoke('read_file', {'path': '../MEMORY.md', '_dataHandle': {
            'namespace': 'stella.knowledge', 'dataDir': str(knowledge)}})
        assert denied['status'] == 'failed'
    finally:
        session.dispose()
    assert (knowledge / 'notes/page.md').is_file()
    assert (tmp_path / 'MEMORY.md').read_text() == 'privatetoken'


def test_memory_worker_does_not_search_knowledge(tmp_path):
    from core.services.memory_gateway import ensure_memory_session
    assert callable(ensure_memory_session)
    memory = tmp_path / 'memory-plugin'
    (memory / 'memory').mkdir(parents=True)
    (memory / 'MEMORY.md').write_text('memorytoken', encoding='utf-8')
    (memory / 'knowledge').mkdir()
    (memory / 'knowledge/private.md').write_text('knowledgetoken', encoding='utf-8')
    session = PluginSession(ROOT.parent / 'memory', source_label='test', registry=PluginRegistry(),
                            user_id='test-user', authz=PluginAuthorizationStore())
    try:
        session.start()
        for query, expected in [('memorytoken', True), ('knowledgetoken', False)]:
            result = session.invoke('search', {'query': query, '_dataHandle': {
                'namespace': 'stella.memory', 'dataDir': str(memory)}})
            assert result['status'] == 'succeeded', result
            assert bool(result['value']['results']) is expected
    finally:
        session.dispose()


def test_knowledge_semantic_search_uses_host_models_without_memory(tmp_path, monkeypatch):
    class Provider:
        dimensions = 2
        def embed_batch(self, texts):
            return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr('models.embedding.create_default_embedding_provider', lambda: Provider())
    folder = tmp_path / 'knowledge'
    folder.mkdir()
    (folder / 'a.md').write_text('# automobile', encoding='utf-8')
    session = PluginSession(ROOT, source_label='test', registry=PluginRegistry(), user_id='test', authz=PluginAuthorizationStore())
    try:
        session.start()
        result = session.invoke('search', {'query': 'car', '_dataHandle': {'namespace': 'stella.knowledge', 'dataDir': str(folder)}})
        assert result['status'] == 'succeeded', result
        assert result['value']['results'], result
    finally:
        session.dispose()


def test_installed_plugins_migrate_preserve_data_and_disable_independently(tmp_path, monkeypatch):
    import json
    import pytest
    from common import state_dir
    from core.plugins import management
    from core.plugins.lifecycle import PluginManager
    from core.plugins.management import ManagementStore
    from core.plugins.package_ops import _sha256_tree
    from core.services import knowledge_gateway, memory_gateway
    from core.services.knowledge_facade import call
    from core.services.memory_facade import MemoryPort
    user = tmp_path / 'user'
    (user / 'knowledge/notes').mkdir(parents=True)
    (user / 'knowledge/notes/old.md').write_text('# Legacy knowledge', encoding='utf-8')
    (user / 'memory').mkdir()
    (user / 'memory/2026-01-01.md').write_text('legacy daily', encoding='utf-8')
    (user / 'MEMORY.md').write_text('legacy preference', encoding='utf-8')
    monkeypatch.setattr(state_dir, 'knowledge_dir', lambda **kwargs: user / 'knowledge')
    monkeypatch.setattr(state_dir, 'memory_dir', lambda **kwargs: user / 'memory')
    monkeypatch.setattr(state_dir, 'memory_file', lambda **kwargs: user / 'MEMORY.md')
    monkeypatch.setattr(state_dir, 'user_root', lambda **kwargs: user)
    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    catalog = tmp_path / 'catalog.json'
    rows = []
    for name in ('knowledge', 'memory'):
        root = ROOT.parent / name
        manifest = json.loads((root / 'plugin.json').read_text())
        rows.append({'pluginId': manifest['id'], 'version': manifest['version'], 'hostApi': manifest['hostApi'],
                     'path': str(root), 'sha256': _sha256_tree(root)})
    catalog.write_text(json.dumps({'coreApi': '1.0.0', 'plugins': rows}))
    manager = PluginManager(store, catalog_path=catalog)
    try:
        for name in ('knowledge', 'memory'):
            manager.install('stella.' + name, user_id='local-default')
        assert 'Legacy' in call('read_file', path='notes/old.md')['content']
        memory = MemoryPort()
        assert memory.read(path='MEMORY.md')['content'] == 'legacy preference'
        assert memory.get_content('2026-01-01.md')['content'] == 'legacy daily'
        memory._call('write', path='MEMORY.md', content=' new', append=True, idempotencyKey='once')
        memory._call('write', path='MEMORY.md', content=' new', append=True, idempotencyKey='once')
        assert memory.read(path='MEMORY.md')['content'] == 'legacy preference new'
        manager.set_intent('stella.knowledge', 'local-default', 'disabled')
        with pytest.raises(PermissionError):
            call('list_tree')
        assert memory.read(path='MEMORY.md')['content'] == 'legacy preference new'
        manager.set_intent('stella.knowledge', 'local-default', 'enabled')
        manager.set_intent('stella.memory', 'local-default', 'disabled')
        with pytest.raises(PermissionError):
            memory.read(path='MEMORY.md')
        assert call('list_tree')['stats']['pages'] == 1
        from bridge.agent_initializer import AgentInitializer
        port, tools = AgentInitializer(None, None)._setup_memory_system(str(user))
        assert not port.is_available()
        assert {tool.name for tool in tools if tool.is_available()} == {'knowledge_search', 'knowledge_get', 'knowledge_write'}
        manager.set_intent('stella.memory', 'local-default', 'enabled')
        manager.adopt_current('stella.memory', user_id='local-default')
        assert memory.read(path='MEMORY.md')['content'] == 'legacy preference new'
        assert (user / 'MEMORY.md').read_text() == 'legacy preference'
        assert (user / 'memory/2026-01-01.md').read_text() == 'legacy daily'
    finally:
        knowledge_gateway.shutdown_knowledge_session()
        memory_gateway.shutdown_memory_session()


def test_model_callback_deadline_bounds_the_host_wait(tmp_path, monkeypatch):
    import time
    import threading
    from core.plugins.host import PluginOutcomeUnknown
    started = threading.Event()
    class SlowProvider:
        dimensions = 2
        def embed_batch(self, texts):
            started.set()
            time.sleep(0.5)
            return [[1., 0.] for _ in texts]
    monkeypatch.setattr('models.embedding.create_default_embedding_provider', lambda: SlowProvider())
    folder = tmp_path / 'knowledge'
    folder.mkdir()
    (folder / 'a.md').write_text('# doc', encoding='utf-8')
    auth = PluginAuthorizationStore()
    session = PluginSession(ROOT, source_label='test', registry=PluginRegistry(), user_id='test', authz=auth)
    try:
        session.start()
        auth.issue(grant_ref='deadline', plugin_id='stella.knowledge', user_id='test',
            capabilities=['knowledge.read','models.embedding'], purposes=['interactive'])
        start = time.monotonic()
        try:
            session.invoke_contract(contract='stella.knowledge@1', method='search', input_payload={'query':'car'},
                origin='system', grant_ref='deadline', timeout_ms=100,
                data_handle={'namespace':'stella.knowledge','dataDir':str(folder)})
        except (PluginOutcomeUnknown, PermissionError):
            pass
        # Lexical fallback can finish at the deadline. Either outcome must
        # stop waiting before the slow model finishes.
        assert started.is_set()
        assert time.monotonic() - start < 0.4
    finally:
        session.dispose()


def test_memory_evolution_restore_does_not_overwrite_a_later_write(tmp_path):
    import uuid
    root = tmp_path / 'memory'
    root.mkdir()
    (root / 'MEMORY.md').write_text('before', encoding='utf-8')
    session = PluginSession(ROOT.parent / 'memory', source_label='test', registry=PluginRegistry(), authz=PluginAuthorizationStore())
    try:
        session.start()
        def call(method, **values):
            return session.invoke_contract(contract='stella.memory@1', method=method, input_payload=values,
                origin='system', grant_ref='snapshot', idempotency_key=uuid.uuid4().hex,
                data_handle={'namespace':'stella.memory','dataDir':str(root)})
        session.authz.issue(grant_ref='snapshot', plugin_id='stella.memory',user_id=session.user_id,
            capabilities=['memory.read','memory.write'],purposes=['interactive'])
        first = call('begin_snapshot')
        assert first['status'] == 'succeeded', first
        snapshot = first['value']['snapshotId']
        call('write', path='MEMORY.md', content='evolved', snapshotId=snapshot)
        assert call('snapshot_status', snapshotId=snapshot)['value']['changed']
        call('write', path='MEMORY.md', content='later accepted')
        refused = call('restore_snapshot', snapshotId=snapshot)
        assert refused['status'] == 'failed'
        assert (root / 'MEMORY.md').read_text() == 'later accepted'
    finally:
        session.dispose()


def test_uninstalled_capabilities_do_not_fall_back_to_sibling_source(tmp_path, monkeypatch):
    import pytest
    from core.plugins import management
    from core.plugins.management import ManagementStore
    from core.services.knowledge_facade import call
    from core.services.memory_facade import MemoryPort
    monkeypatch.setattr(management, 'default_store', lambda: ManagementStore(tmp_path / 'packages'))
    monkeypatch.delenv('STELLA_KNOWLEDGE_PLUGIN', raising=False)
    monkeypatch.delenv('STELLA_MEMORY_PLUGIN', raising=False)
    with pytest.raises(PermissionError):
        call('list_tree')
    with pytest.raises(PermissionError):
        MemoryPort().read(path='MEMORY.md')


def test_memory_restore_serializes_with_a_second_worker_write(tmp_path):
    import shutil
    import threading
    import time
    import uuid
    package = tmp_path / 'package'
    shutil.copytree(ROOT.parent / 'memory', package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    implementation = package / 'backend/memory_domain/documents.py'
    source = implementation.read_text().replace('        os.replace(staged, target)', '''        if result == 'before':
            (root / '.restore-checked').write_text('ready')
            import time
            time.sleep(0.3)
        os.replace(staged, target)''')
    implementation.write_text(source)
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'MEMORY.md').write_text('before')
    sessions = [PluginSession(package, source_label='test', registry=PluginRegistry(), authz=PluginAuthorizationStore()) for _ in range(2)]
    outcomes = []
    def call(session, method, **values):
        return session.invoke_contract(contract='stella.memory@1', method=method, input_payload=values,
            origin='system', grant_ref='lock-test', idempotency_key=uuid.uuid4().hex,
            data_handle={'namespace':'stella.memory','dataDir':str(data)})
    try:
        for session in sessions:
            session.start()
            session.authz.issue(grant_ref='lock-test',plugin_id='stella.memory',user_id=session.user_id,
                capabilities=['memory.read','memory.write'],purposes=['interactive'])
        snapshot = call(sessions[0], 'begin_snapshot')['value']['snapshotId']
        assert call(sessions[0], 'write', path='MEMORY.md', content='evolved', snapshotId=snapshot)['status'] == 'succeeded'
        worker = threading.Thread(target=lambda: outcomes.append(call(sessions[0], 'restore_snapshot', snapshotId=snapshot)))
        worker.start()
        limit = time.monotonic() + 3
        while not (data / '.restore-checked').exists() and time.monotonic() < limit:
            time.sleep(0.01)
        assert (data / '.restore-checked').exists()
        assert call(sessions[1], 'write', path='MEMORY.md', content='later accepted')['status'] == 'succeeded'
        worker.join(3)
        assert not worker.is_alive()
        assert outcomes[0]['status'] == 'succeeded'
        assert (data / 'MEMORY.md').read_text() == 'later accepted'
    finally:
        for session in sessions:
            session.dispose()


def test_memory_search_forgets_deleted_documents_and_rebuilds_unchanged_files(tmp_path, monkeypatch):
    calls = []
    class Provider:
        dimensions = 2
        model = 'test-model'
        def embed_batch(self, texts):
            calls.extend(texts)
            return [[1., 0.] for _ in texts]
    monkeypatch.setattr('models.embedding.create_default_embedding_provider', lambda: Provider())
    root = tmp_path / 'memory'
    (root / 'memory').mkdir(parents=True)
    file = root / 'memory/a.md'
    file.write_text('deletabletoken')
    session = PluginSession(ROOT.parent / 'memory', source_label='test', registry=PluginRegistry(), authz=PluginAuthorizationStore())
    try:
        session.start()
        def invoke(method, **values):
            import uuid
            return session.invoke_contract(contract='stella.memory@1', method=method, input_payload=values,
                origin='system', grant_ref='rebuild', idempotency_key=uuid.uuid4().hex,
                data_handle={'namespace':'stella.memory','dataDir':str(root)})
        session.authz.issue(grant_ref='rebuild',plugin_id='stella.memory',user_id=session.user_id,
            capabilities=['memory.read','memory.write','models.embedding'],purposes=['interactive'])
        assert invoke('search', query='deletabletoken')['value']['results']
        before = len(calls)
        assert invoke('sync', force=True)['status'] == 'succeeded'
        assert len(calls) > before
        before = len(calls)
        Provider.model = 'replacement-model'
        assert invoke('search', query='deletabletoken')['value']['results']
        assert len(calls) == before + 2, 'model changes must re-embed both source and query'
        file.unlink()
        assert invoke('search', query='deletabletoken')['value']['results'] == []
    finally:
        session.dispose()


def test_memory_embedding_proxy_batches_and_keeps_model_identity(monkeypatch):
    import sys
    from types import SimpleNamespace
    from memory_domain.embedding.host import create_default_embedding_provider
    batches = []
    def invoke(contract, method, values):
        if method == 'embedding_status':
            return {'status': 'succeeded', 'value': {'dimensions': 2, 'provider': 'example', 'model': 'v2'}}
        batches.append(values['texts'])
        assert len(values['texts']) <= 24
        return {'status': 'succeeded', 'value': {'vectors': [[1., 0.] for _ in values['texts']]}}
    monkeypatch.setitem(sys.modules, 'stella_host', SimpleNamespace(invoke=invoke))
    provider = create_default_embedding_provider()
    assert len(provider.embed_batch(['text'] * 145)) == 145
    assert provider.model == 'v2'
    assert provider.provider == 'example'
    assert len(batches) == 7


def test_memory_worker_remembers_flushed_messages_between_requests(tmp_path, monkeypatch):
    from models.plugin_service import bind_model, reset_model
    import uuid
    class Model:
        def call(self, request):
            return {'content': 'A durable daily summary'}
    root = tmp_path / 'memory'
    session = PluginSession(ROOT.parent / 'memory', source_label='test', registry=PluginRegistry(), authz=PluginAuthorizationStore())
    token = bind_model(Model())
    try:
        session.start()
        session.authz.issue(grant_ref='flush', plugin_id='stella.memory', user_id=session.user_id,
            capabilities=['memory.write','models.chat'], purposes=['interactive'])
        def flush(messages):
            return session.invoke_contract(contract='stella.memory@1', method='flush_memory', input_payload={'messages':messages},
                origin='system',grant_ref='flush',idempotency_key=uuid.uuid4().hex,
                data_handle={'namespace':'stella.memory','dataDir':str(root)})
        messages = [{'role':'user','content':'I work on project Stella and prefer concise answers.'}]
        assert flush(messages)['value']['flushed'] is True
        assert 'A durable daily summary' in next((root / 'memory').glob('*.md')).read_text()
        assert flush(messages)['value']['flushed'] is False
    finally:
        reset_model(token)
        session.dispose()


def test_memory_worker_does_not_import_host_configuration():
    import ast
    for source in (ROOT.parent / 'memory/backend').rglob('*.py'):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module != 'config', source
            elif isinstance(node, ast.Import):
                assert all(alias.name != 'config' for alias in node.names), source


def test_memory_summary_never_writes_after_cancellation_or_outside_namespace(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from datetime import datetime
    from memory_domain.summarizer import MemoryFlushManager
    root = tmp_path / 'plugin'
    root.mkdir()
    manager = MemoryFlushManager(root)
    monkeypatch.setitem(sys.modules, 'stella_host', SimpleNamespace(cancellation_token=lambda: SimpleNamespace(is_set=lambda: True)))
    assert manager.write_daily_summary('cancelled summary') is False
    assert not list((root / 'memory').glob('*.md'))
    monkeypatch.delitem(sys.modules, 'stella_host')
    outside = tmp_path / 'outside.md'
    outside.write_text('original')
    today = datetime.now().strftime('%Y-%m-%d')
    (root / 'memory' / f'{today}.md').symlink_to(outside)
    assert manager.write_daily_summary('escape summary') is False
    assert outside.read_text() == 'original'


def test_cancelled_flush_does_not_consume_the_messages_for_retry(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from memory_domain.summarizer import MemoryFlushManager
    cancelled = [True]
    monkeypatch.setitem(sys.modules, 'stella_host', SimpleNamespace(cancellation_token=lambda: SimpleNamespace(is_set=lambda: cancelled[0])))
    manager = MemoryFlushManager(tmp_path)
    messages = [{'role': 'user', 'content': 'Record the project decision for tomorrow.'}]
    assert manager.flush_from_messages(messages) is False
    cancelled[0] = False
    assert manager.flush_from_messages(messages) is True
    assert list((tmp_path / 'memory').glob('*.md'))


def test_core_context_does_not_offer_uninstalled_memory_or_knowledge(tmp_path, monkeypatch):
    from agent.prompt import workspace, builder
    monkeypatch.setattr('common.state_dir.user_root_for_workspace', lambda _: tmp_path)
    workspace.ensure_workspace(str(tmp_path))
    rule = (tmp_path / 'RULE.md').read_text()
    assert 'knowledge/' not in rule and 'MEMORY.md' not in rule
    section = '\n'.join(builder._build_workspace_section(str(tmp_path), 'en', context_files_loaded=True))
    assert 'MEMORY.md' not in section


def test_partial_memory_restore_reports_unknown_and_can_resume(tmp_path):
    import shutil
    import uuid
    from core.plugins.host import PluginOutcomeUnknown
    import pytest
    package = tmp_path / 'package'
    shutil.copytree(ROOT.parent / 'memory', package, ignore=shutil.ignore_patterns('__pycache__'))
    source = package / 'backend/memory_domain/documents.py'
    source.write_text(source.read_text().replace('    check_active()\n    target =',
        "    if path == 'memory/b.md' and content == 'before-b' and (root / '.fail-restore').exists():\n        raise PermissionError('injected cancellation')\n    check_active()\n    target =", 1))
    root = tmp_path / 'memory'
    (root / 'memory').mkdir(parents=True)
    (root / 'MEMORY.md').write_text('before-a')
    (root / 'memory/b.md').write_text('before-b')
    session = PluginSession(package, source_label='test', registry=PluginRegistry(), authz=PluginAuthorizationStore())
    try:
        session.start()
        session.authz.issue(grant_ref='restore', plugin_id='stella.memory',user_id=session.user_id,
            capabilities=['memory.read','memory.write'],purposes=['interactive'])
        def call(method, key=None, **values):
            return session.invoke_contract(contract='stella.memory@1', method=method,input_payload=values,
                origin='system',grant_ref='restore',idempotency_key=key or uuid.uuid4().hex,
                data_handle={'namespace':'stella.memory','dataDir':str(root)})
        snapshot = call('begin_snapshot')['value']['snapshotId']
        call('write', path='MEMORY.md', content='after-a',snapshotId=snapshot)
        call('write', path='memory/b.md', content='after-b',snapshotId=snapshot)
        (root / '.fail-restore').touch()
        with pytest.raises(PluginOutcomeUnknown):
            call('restore_snapshot',key='undo-once',snapshotId=snapshot)
        assert (root / 'MEMORY.md').read_text() == 'before-a'
        assert (root / 'memory/b.md').read_text() == 'after-b'
        assert call('restore_snapshot',key='undo-once',snapshotId=snapshot)['status'] == 'unknown'
        (root / '.fail-restore').unlink()
        assert call('restore_snapshot',snapshotId=snapshot)['status'] == 'succeeded'
        assert (root / 'memory/b.md').read_text() == 'before-b'
        assert call('restore_snapshot',snapshotId=snapshot)['status'] == 'succeeded'
    finally:
        session.dispose()


def test_memory_query_initialization_never_creates_authoritative_documents(tmp_path):
    from memory_domain.config import MemoryConfig
    from memory_domain.manager import MemoryManager
    manager = MemoryManager(MemoryConfig(workspace_root=str(tmp_path)))
    try:
        assert not (tmp_path / 'MEMORY.md').exists()
    finally:
        manager.close()


def test_memory_service_refuses_a_symlinked_content_directory(tmp_path):
    from memory_domain.service import MemoryService
    import pytest
    root = tmp_path / 'plugin'
    root.mkdir()
    outside = tmp_path / 'private'
    outside.mkdir()
    (outside / 'secret.md').write_text('private content')
    (root / 'memory').symlink_to(outside, target_is_directory=True)
    service = MemoryService(str(root))
    assert service.list_files()['list'] == []
    with pytest.raises(ValueError):
        service.get_content('secret.md')


def test_domain_queries_preserve_search_and_read_permission_distinction(monkeypatch):
    from core.plugins.host import _conversation_permission_denial
    seen = []
    monkeypatch.setattr('agent.runtime.tool_invocation.permission_denial', lambda tool, args, **kw: seen.append(tool))
    for domain in ('memory', 'knowledge'):
        for method in ('search', 'read', 'write'):
            _conversation_permission_denial(contract=f'stella.{domain}@1', method=method,
                agent_id='agent', session_id='session', effect='domainWrite' if method == 'write' else 'query')
    assert seen == ['memory_search', 'memory_get', 'memory_write', 'knowledge_search', 'knowledge_get', 'knowledge_write']


def test_model_service_rejects_request_overrides_and_undeclared_callbacks(tmp_path):
    import pytest
    from models.plugin_service import _invoke
    from core.plugins.core_invoke import dispatch
    for field, value in [('model', 'override'), ('tools', []), ('api_key', 'override')]:
        with pytest.raises(ValueError):
            _invoke('complete', {'request': {'messages': [], field: value}})
    session = PluginSession(ROOT.parent / 'memory', source_label='test', registry=PluginRegistry(), authz=PluginAuthorizationStore())
    try:
        session.start()
        context = {'userId': session.user_id, 'invocationRef': 'bound-invocation', 'grantRef': 'read-only'}
        with pytest.raises(PermissionError, match='not declared'):
            dispatch(session, {'contract':'stella.models@1','method':'complete','input':{'request':{'messages':[]}},
                'deadline':'2099-01-01T00:00:00Z','invocationRef':'bound-invocation'},
                {'contract':'stella.memory@1','method':'get_context','deadline':'2099-01-01T00:00:00Z','context':context})
    finally:
        session.dispose()


def test_builtin_skills_do_not_inject_legacy_knowledge_instructions(tmp_path):
    from agent.skills.manager import SkillManager
    manager = SkillManager(custom_dir=str(tmp_path / 'skills'))
    assert 'knowledge-wiki' not in manager.skills
