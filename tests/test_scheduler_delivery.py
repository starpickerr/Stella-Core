from types import SimpleNamespace
from pathlib import Path
import pytest
from agent.runtime.tool_invocation import permission_denial
from agent.scheduler import delivery, integration
from agent.tools.base_tool import ToolResult


@pytest.mark.parametrize('source,folder', [('source','project'),(None,'workspace')])
def test_scheduled_relative_write_uses_same_cwd_as_policy(tmp_path, monkeypatch, source, folder):
    from agent.tools.write.write import Write
    from agent.runtime.run_record import RunRecord
    workspace=tmp_path/'workspace';project=tmp_path/'project';workspace.mkdir();project.mkdir()
    monkeypatch.setattr('agent.workspace.project_store.get_project_dir',lambda session,agent: str(project) if session=='source' else None)
    monkeypatch.setattr('agent.workspace.session_prefs.get_prefs',lambda *_: {'permission':'workspace-write'})
    monkeypatch.setattr('agent.runtime.tool_invocation.global_mode',lambda:'workspace-write')
    monkeypatch.setattr(integration,'_resolve_workspace',lambda **_:str(workspace))
    monkeypatch.setattr('agent.runtime.run_record.RunRecord',lambda:RunRecord(tmp_path/'runs.db'))
    monkeypatch.setattr('agent.tools.tool_manager.ToolManager',lambda:SimpleNamespace(create_tool=lambda _:Write()))
    task={'id':'write','action':{'execution_session_id':source}}
    result=integration._run_scheduled_tool(task,'write',{'path':'scheduled-probe.txt','content':'saved'},None,None,None)
    assert (tmp_path/folder/'scheduled-probe.txt').read_text()=='saved'
    assert not (tmp_path/('workspace' if folder=='project' else 'project')/'scheduled-probe.txt').exists()
    assert permission_denial('write',{'path':str(Path.home()/'stella-policy-escape.txt')},session_id=source,workspace=str(workspace))


def test_destination_change_preserves_source_and_cleans_old_fields(monkeypatch):
    monkeypatch.setattr(delivery,'runtime_channel',lambda _:SimpleNamespace())
    old={'type':'agent_task','notify_session_id':'source','channel_type':'feishu','receiver':'oc_old','is_group':True,'receive_id_type':'chat_id','dingtalk_sender_staff_id':'obsolete'}
    result=delivery.patch_destination(old,{'channel_type':'web','receiver':'target'})
    assert result['execution_session_id']=='source'
    assert result['notify_session_id']=='target'
    assert 'receive_id_type' not in result and 'dingtalk_sender_staff_id' not in result


def test_weixin_missing_token_is_explicit(monkeypatch):
    monkeypatch.setattr(delivery,'runtime_channel',lambda _:SimpleNamespace(_context_tokens={}))
    with pytest.raises(ValueError,match='conversation'):
        delivery.normalize_destination({'channel_type':'weixin','receiver':'u'})


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
    job=store.claim_occurrence('cached',manual=True);task['job_run_id']=job
    calls=[]; sent=[]
    def execute(_): calls.append('executed');return ToolResult.success('saved result')
    def send(reply,context): sent.append(context['receive_id_type']);return len(sent)>1
    monkeypatch.setattr('agent.tools.tool_manager.ToolManager',lambda:SimpleNamespace(create_tool=lambda _:SimpleNamespace(execute=execute)))
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
