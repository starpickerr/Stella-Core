from types import SimpleNamespace
from pathlib import Path
import sys
import pytest
from agent.runtime.tool_invocation import permission_denial
from agent.scheduler import delivery, integration
from agent.tools.base_tool import ToolResult


@pytest.mark.parametrize('source,folder', [('source','project'),(None,'work/automations/alpha/write')])
def test_scheduled_relative_write_uses_same_cwd_as_policy(tmp_path, monkeypatch, source, folder, registered_agent):
    from agent.tools.write.write import Write
    from agent.runtime.run_record import RunRecord
    registered_agent('alpha')
    workspace = tmp_path / 'work'
    project = tmp_path / 'project'
    workspace.mkdir()
    project.mkdir()
    monkeypatch.setattr('agent.workspace.project_store.get_project_dir',lambda session,agent: str(project) if session=='source' else None)
    monkeypatch.setattr('agent.workspace.project_store.get_project_binding',lambda session,agent: str(project) if session=='source' else None)
    monkeypatch.setattr('agent.workspace.context.personal_work_dir',lambda **kwargs: workspace)
    monkeypatch.setattr('agent.workspace.session_prefs.get_prefs',lambda *_: {'permission':'workspace-write'})
    monkeypatch.setattr('agent.runtime.tool_invocation.global_mode',lambda:'workspace-write')
    monkeypatch.setattr(integration,'_resolve_working_dir',lambda **_:str(workspace))
    monkeypatch.setattr('agent.runtime.run_record.RunRecord',lambda:RunRecord(tmp_path/'runs.db'))
    monkeypatch.setattr('agent.tools.tool_manager.ToolManager',lambda:SimpleNamespace(create_tool=lambda _:Write()))
    task={'id':'write','action':{'execution_session_id':source}}
    integration._run_scheduled_tool(task,'write',{'path':'scheduled-probe.txt','content':'saved'},'alpha',None,None)
    assert (tmp_path/folder/'scheduled-probe.txt').read_text()=='saved'
    assert not (tmp_path/('work/automations/alpha/write' if folder=='project' else 'project')/'scheduled-probe.txt').exists()
    assert permission_denial('write',{'path':str(Path.home()/'stella-policy-escape.txt')},session_id=source,workspace=str(workspace))


def test_task_permission_applies_only_during_the_run(tmp_path, monkeypatch, registered_agent):
    import threading
    from agent.permission.gateway import SecurityGateway
    from agent.runtime.run_record import RunRecord
    from agent.runtime.tool_invocation import permission_denial, scheduled_permission_scope
    registered_agent('alpha')
    workspace = tmp_path / 'work'
    workspace.mkdir()
    monkeypatch.setattr('agent.workspace.context.personal_work_dir', lambda **kwargs: workspace)
    monkeypatch.setattr('agent.workspace.session_prefs.get_prefs', lambda *_args, **_kwargs: {
        'security_policy': {'preset': 'workspace-write', 'rules': {}}})
    monkeypatch.setattr('agent.runtime.tool_invocation.global_mode', lambda: 'workspace-write')
    monkeypatch.setattr(integration, '_resolve_working_dir', lambda **_kwargs: str(workspace))
    monkeypatch.setattr('agent.runtime.run_record.RunRecord', lambda: RunRecord(tmp_path / 'runs.db'))
    calls = []
    monkeypatch.setattr('agent.tools.tool_manager.ToolManager', lambda: SimpleNamespace(
        create_tool=lambda _name: SimpleNamespace(execute_tool=lambda params: calls.append(params) or ToolResult.success('ok'),
                                                  config={})))
    inherited = {'id': 'inherit', 'action': {'execution_session_id': 'source', 'silent': True}}
    started = threading.Event()

    def slow_wait(*_args, **_kwargs):
        started.set()
        raise AssertionError('approval wait')

    monkeypatch.setattr(SecurityGateway, 'wait_for_decision', slow_wait)
    blocked = integration._run_scheduled_tool(inherited, 'bash', {'command': 'git push origin main'},
                                              'alpha', threading.Event(), None)
    assert blocked.status == 'failed'
    assert calls == []
    assert not started.is_set()
    explicit = {'id': 'full', 'run_permission_mode': 'full-access',
                'action': {'execution_session_id': 'source', 'silent': True}}
    allowed = integration._run_scheduled_tool(explicit, 'bash', {'command': 'git push origin main'},
                                              'alpha', threading.Event(), None)
    assert allowed == 'ok'
    assert calls == [{'command': 'git push origin main'}]
    later = permission_denial('bash', {'command': 'git push origin main'}, session_id='source', noninteractive=True)
    assert later and 'Authorization required' in later
    from agent.workspace.context import resolve_context
    owner = resolve_context('owner', 'alpha', ensure=True)
    secret = owner.root / 'secret.txt'
    secret.write_text('secret')
    with scheduled_permission_scope('full-access'):
        denied = permission_denial('read', {'path': str(secret)}, session_id='source', noninteractive=True)
    assert denied and 'private' in denied.lower()
    readonly = integration._run_scheduled_tool(
        {'id': 'ro', 'run_permission_mode': 'read-only', 'action': {'execution_session_id': 'source', 'silent': True}},
        'write', {'path': 'note.txt', 'content': 'no'}, 'alpha', None, None)
    assert readonly.status == 'failed'


def test_scheduled_confirmation_exits_as_pending_without_running_tool(tmp_path, monkeypatch, caplog):
    from agent.runtime.run_record import RunRecord
    from common.log import logger

    monkeypatch.setattr('agent.runtime.run_record.RunRecord', lambda: RunRecord(tmp_path/'runs.db'))
    monkeypatch.setattr('agent.runtime.tool_invocation.permission_denial',
                        lambda *_args, **_kwargs: 'Authorization required. Adjust the policy and rerun manually.')
    monkeypatch.setattr(integration, '_resolve_working_dir', lambda **_: str(tmp_path))
    monkeypatch.setattr('agent.tools.tool_manager.ToolManager',
                        lambda: SimpleNamespace(create_tool=lambda _: pytest.fail('tool must not run')))
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING", logger=logger.name):
            result = integration._run_scheduled_tool(
                {'id': 'pending', 'action': {}}, 'bash', {'command': 'echo hi'},
                None, None, None)
    finally:
        logger.removeHandler(caplog.handler)
    assert result.status == 'failed' and not result.retryable
    assert 'Authorization required' in result.error
    assert 'Scheduled deny tool=bash' in caplog.text


def test_destination_change_preserves_source_and_cleans_old_fields(monkeypatch):
    monkeypatch.setattr(delivery,'runtime_channel',lambda _:SimpleNamespace())
    old={'type':'agent_task','notify_session_id':'source','channel_type':'feishu','receiver':'oc_old','is_group':True,'receive_id_type':'chat_id','dingtalk_sender_staff_id':'obsolete'}
    result=delivery.patch_destination(old,{'channel_type':'web','receiver':'target'})
    assert result['execution_session_id']=='source'
    assert result['notify_session_id']=='target'
    assert 'receive_id_type' not in result and 'dingtalk_sender_staff_id' not in result


def test_weixin_missing_token_is_explicit(monkeypatch):
    monkeypatch.setattr(delivery,'runtime_channel',lambda _:SimpleNamespace(_context_tokens={}, login_status='logged_in'))
    with pytest.raises(ValueError,match='conversation'):
        delivery.normalize_destination({'channel_type':'weixin','receiver':'u'})


def test_runtime_channel_uses_running_main_module(monkeypatch):
    channel = SimpleNamespace(_context_tokens={'user-1': 'private-token'}, login_status='logged_in')
    manager = SimpleNamespace(get_channel=lambda name: channel if name == 'weixin' else None)
    monkeypatch.setattr(sys.modules['__main__'], '_channel_mgr', manager, raising=False)
    assert delivery.runtime_channel('weixin') is channel
    assert [row['channel_type'] for row in delivery.destination_catalog()] == []
    assert 'private-token' not in str(delivery.destination_catalog())


def test_weixin_is_absent_from_the_proactive_catalog(monkeypatch):
    channel = SimpleNamespace(_context_tokens={}, login_status='logged_in')
    monkeypatch.setattr(delivery, 'runtime_channel', lambda name: channel if name == 'weixin' else None)
    assert delivery.destination_catalog() == []


def test_configured_weixin_is_not_offered_for_proactive_delivery(monkeypatch):
    monkeypatch.setattr(delivery, 'runtime_channel', lambda _: None)
    monkeypatch.setattr(delivery, 'desktop_client_connected', lambda: False)
    monkeypatch.setattr('config.conf', lambda: {'channel_type': 'web,weixin'})
    assert delivery.destination_catalog() == []


def test_weixin_readiness_checks_the_running_channel(monkeypatch):
    running = SimpleNamespace(_context_tokens={'user-1': 'private-token'}, login_status='logged_in')
    monkeypatch.setattr(delivery, 'runtime_channel', lambda name: running if name == 'weixin' else None)
    monkeypatch.setattr('channel.channel_factory.create_channel', lambda _: SimpleNamespace(_context_tokens={}))
    assert integration._is_channel_ready('weixin', 'user-1') is True
    assert integration._is_channel_ready('weixin', 'other-user') is False


def test_weixin_scheduled_message_sends_on_running_channel(monkeypatch):
    sent = []
    running = SimpleNamespace(send=lambda reply, context: sent.append((reply.content, context['receiver'])) or True)
    monkeypatch.setattr(delivery, 'runtime_channel', lambda name: running if name == 'weixin' else None)
    monkeypatch.setattr('channel.channel_factory.create_channel', lambda _: pytest.fail('must not construct a new Weixin channel'))
    monkeypatch.setattr(integration, '_remember_delivered_output', lambda *_args, **_kwargs: True)
    task = {'id': 'weixin-task', 'action': {'type': 'send_message', 'content': 'Hello',
                                           'channel_type': 'weixin', 'receiver': 'user-1'}}
    assert integration._execute_send_message(task, None) is True
    assert sent == [('Hello', 'user-1')]


def test_weixin_catalog_marks_known_expired_session_until_new_context(monkeypatch):
    from channel.weixin.weixin_channel import WeixinChannel
    channel = WeixinChannel()
    channel.login_status = channel.LOGIN_STATUS_OK
    channel._context_tokens = {'user-1': 'old-token'}
    monkeypatch.setattr(channel, '_persist_context_tokens_locked', lambda: None)
    with pytest.raises(RuntimeError, match='-14'):
        channel._check_send_response({'ret': -14}, 'user-1')
    monkeypatch.setattr(delivery, 'runtime_channel', lambda name: channel if name == 'weixin' else None)
    assert delivery.destination_catalog() == []


def test_weixin_unknown_login_state_cannot_be_scheduled(monkeypatch):
    channel = SimpleNamespace(_context_tokens={'user-1': 'private-token'})
    monkeypatch.setattr(delivery, 'runtime_channel', lambda name: channel if name == 'weixin' else None)
    assert delivery.destination_catalog() == []
    with pytest.raises(ValueError, match='login'):
        delivery.normalize_destination({'channel_type': 'weixin', 'receiver': 'user-1'})


def test_route_defaults_to_no_destination(monkeypatch):
    assert delivery.normalize_notification_route(None) == {
        'primary': None, 'needs_reselect': False,
    }


def test_disabled_backup_field_is_not_stored(monkeypatch):
    route = delivery.normalize_notification_route({
        'primary': {'channel_type': 'telegram', 'receiver': '100'},
        'backup_enabled': False,
        'backup': None,
    })
    assert route == {'primary': {'channel_type': 'telegram', 'receiver': '100', 'is_group': False,
                                 'receiver_name': '100', 'notify_session_id': '100'},
                     'needs_reselect': False}


def test_route_rejects_backup_and_missing_recipient(monkeypatch):
    with pytest.raises(ValueError, match='备用渠道已移除'):
        delivery.normalize_notification_route({
            'primary': {'channel_type': 'telegram', 'receiver': '100'},
            'backup_enabled': True,
            'backup': {'channel_type': 'desktop', 'receiver': 'client'},
        })
    with pytest.raises(ValueError, match='recipient'):
        delivery.normalize_notification_route({'primary': {'channel_type': 'telegram'}})
    with pytest.raises(ValueError, match='备用渠道已移除'):
        delivery.normalize_notification_route({
            'primary': {'channel_type': 'telegram', 'receiver': '100'}, 'backup_enabled': True,
        })


def test_false_send_is_a_delivery_failure():
    with pytest.raises(RuntimeError,match='rejected'):
        integration._send_checked(SimpleNamespace(send=lambda *_:False),None,{})


def test_weixin_send_timeout_never_acknowledges_delivery(monkeypatch):
    import requests
    from channel.weixin.weixin_api import WeixinApi
    def timeout(*args,**kwargs): raise requests.exceptions.Timeout('unknown')
    monkeypatch.setattr(requests,'post',timeout)
    api=WeixinApi('https://example.invalid','fake')
    assert api.get_updates()=={'ret':0,'msgs':[]}
    with pytest.raises(requests.exceptions.Timeout):
        api.send_text('fake-user','test','fake-token')


def test_delivery_retry_reuses_completed_tool_output(tmp_path,monkeypatch):
    from agent.registry import get_agent_registry
    from agent.scheduler.automation_store import AutomationStore
    from agent.runtime.run_record import RunRecord
    from common.runtime_identity import identity_scope
    agent_id=get_agent_registry().default_agent_id
    store=AutomationStore(tmp_path/'scheduler'/'tasks.json',agent_id)
    task={'id':'cached','name':'cached','schedule':{'type':'once','run_at':'2026-10-02T00:00:00'},'action':{'type':'tool_call','call_name':'test','receiver':'recipient','channel_type':'feishu','receive_id_type':'email','call_params':{}}}
    store.add_task(task)
    job=store.claim_occurrence('cached',manual=True)
    task['job_run_id']=job
    calls=[]
    sent=[]
    def execute(_):
        calls.append('executed')
        return ToolResult.success('saved result')
    def send(reply,context):
        sent.append(context['receive_id_type'])
        return len(sent)>1
    monkeypatch.setattr('agent.tools.tool_manager.ToolManager',lambda:SimpleNamespace(create_tool=lambda _:SimpleNamespace(execute_tool=execute)))
    monkeypatch.setattr('agent.runtime.tool_invocation.permission_denial',lambda *_a,**_k:None)
    monkeypatch.setattr('agent.runtime.run_record.RunRecord',lambda:RunRecord(tmp_path/'runs.db'))
    monkeypatch.setattr('agent.scheduler.result_cache.runs_dir',lambda **_:tmp_path)
    monkeypatch.setattr(integration,'get_task_store',lambda **_:store)
    monkeypatch.setattr('channel.channel_factory.create_channel',lambda _:SimpleNamespace(send=send))
    with identity_scope(agent_id=agent_id):
        assert integration._execute_tool_call(task,None,agent_id) is False
        store.finish_occurrence(job,False)
        assert integration._execute_tool_call(task,None,agent_id) is True
    assert calls==['executed']
    assert sent==['email','email']
