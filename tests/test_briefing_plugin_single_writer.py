"""Briefing action decisions and outbox stay in its worker, including peer writes."""
from pathlib import Path
import sqlite3

from core.plugins.authz import PluginAuthorizationStore
from core.plugins.management import ManagementStore
from core.plugins.package_ops import PackageStore
from core.services import briefing_gateway


def test_briefing_creates_and_recovers_todo_through_scoped_reverse_call(tmp_path, monkeypatch):
    from core.plugins import management
    from core.plugins.authorization import AuthorizationService
    from core.services import todos_gateway, calendar_gateway, briefing_facade
    from common import state_dir

    store = ManagementStore(tmp_path / 'packages')
    packages = PackageStore(store.root)
    authz = PluginAuthorizationStore()
    monkeypatch.setattr(management, 'default_store', lambda: store)
    for domain, gateway in [('briefing', briefing_gateway), ('tasks', todos_gateway), ('calendar', calendar_gateway)]:
        getattr(gateway, f'shutdown_{"todos" if domain == "tasks" else domain}_session')()
        op = packages.stage(Path(f'stella-plugins-workspace/plugins/{domain}'))
        packages.inspect(op.operation_id)
        packages.prepare(op.operation_id)
        packages.commit(op.operation_id)
        store.set_intent(f'stella.{domain}', 'local-default', 'enabled')
        monkeypatch.setattr(gateway, 'DEFAULT_AUTHZ', authz)
    for name in ('briefing', 'todos', 'calendar'):
        monkeypatch.setattr(state_dir, name + '_db', lambda ensure=True, name=name: tmp_path / f'{name}.sqlite')
    service = AuthorizationService(store, authz)
    for domain in ('briefing', 'tasks', 'calendar'):
        methods = service.describe(f'stella.{domain}', 'local-default')[0]['methods']
        for capability in sorted({cap for method in methods for cap in method['permissions']}):
            request = service.request(f'stella.{domain}', 'local-default', {'consumerPluginId':'stella.briefing',
                'capability':capability, 'methods':[method['name'] for method in methods if capability in method['permissions']],
                'resources':[{'kind':'user','id':'local-default'}], 'purpose':'interactive'})
            service.approve('local-default', request['requestId'])

    def ok(method, **params):
        result = briefing_gateway.invoke_briefing(method, params, db_path=tmp_path / 'briefing.sqlite')
        assert result['status'] == 'succeeded', result
        return result.get('value')

    try:
        source = ok('upsert_source_item', payload={'source':'email','account_id':'account','source_id':'message',
            'title':'完成作业','snippet':'due','occurred_at':'2026-10-18T08:00:00Z', 'payload':{'information_type':'assignment'}})['item']
        ok('start_briefing', briefing_date='2026-10-18')
        detail = ok('complete_briefing', briefing_id='brf-2026-10-18', payload={'status':'completed',
            'items':[{'source_item_id':source['id'],'section':'action','title':'完成作业','payload':{'information_type':'assignment'}}],
            'mail':[{'id':source['id'],'source':'email','account_id':'account','source_id':'message','title':'完成作业',
                'occurred_at':'2026-10-18T08:00:00Z','category':'selected','metadata':{'information_type':'assignment'},
                'decision':{'category':'needs_action','section':'action'}}]})
        item_id = detail['items'][0]['id']
        first = ok('update_action', item_id=item_id, payload={'operation':'create','kind':'todo'})
        repeated = ok('update_action', item_id=item_id, payload={'operation':'create','kind':'todo'})
        assert first['target_id'] == repeated['target_id']
        with sqlite3.connect(tmp_path / 'todos.sqlite') as db:
            assert db.execute('SELECT COUNT(*) FROM todos').fetchone()[0] == 1
        # This public facade must route all decision operations to the owner.
        monkeypatch.setattr(briefing_facade, '_db_path', lambda: tmp_path / 'briefing.sqlite')
        import importlib.util
        assert importlib.util.find_spec('agent.briefing.service') is None
        assert briefing_facade.BriefingPluginFacade().get_action_targets('todo', '作业')
    finally:
        for domain, gateway in [('briefing', briefing_gateway), ('todos', todos_gateway), ('calendar', calendar_gateway)]:
            getattr(gateway, f'shutdown_{domain}_session')()
