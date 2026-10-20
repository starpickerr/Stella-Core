"""User intent persists independently of availability and execution authorization."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest

from agent.tools.capability_settings import CapabilitySettings


def test_preferences_default_without_creating_files_and_survive_recreation(tmp_path):
    first = CapabilitySettings(str(tmp_path / 'workspace'), user_id='alice')
    assert first.enabled('tool', 'read')
    assert first.enabled('mcp', 'Documents')
    assert not first.path.exists()
    first.set_enabled('tool', 'read', False)
    assert not CapabilitySettings(str(tmp_path / 'workspace'), user_id='alice').enabled('tool', 'read')
    first.set_enabled('tool', 'read', True)
    assert CapabilitySettings(str(tmp_path / 'workspace'), user_id='alice').enabled('tool', 'read')


def test_preferences_isolate_users_workspaces_and_concurrent_updates(tmp_path):
    a = CapabilitySettings(str(tmp_path / 'a'), user_id='alice')
    b = CapabilitySettings(str(tmp_path / 'b'), user_id='alice')
    other = CapabilitySettings(str(tmp_path / 'a'), user_id='bob')
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda name: a.set_enabled('tool', name, False), ['read','write','bash','edit']))
    assert all(not a.enabled('tool', name) for name in ['read','write','bash','edit'])
    assert b.enabled('tool','read') and other.enabled('tool','read')
    assert not a.enabled('mcp','Documents',default=False)


@pytest.mark.parametrize('kind,name,value', [('tool','read','false'),('mcp','Documents',0),
    ('other','read',False),('tool','../read',False),('mcp','bad\x00name',False)])
def test_preferences_reject_invalid_input_without_writes(tmp_path,kind,name,value):
    store = CapabilitySettings(str(tmp_path),user_id='alice')
    with pytest.raises(ValueError):
        store.set_enabled(kind,name,value)
    assert not store.path.exists()


def test_cached_tool_refuses_after_disable_even_inside_existing_invocation(tmp_path,monkeypatch):
    from agent.tools.base_tool import BaseTool, ToolResult, is_tool_available
    from agent.runtime.tool_invocation import invocation_scope, permission_denial
    calls=[]
    class Read(BaseTool):
        name='read'
        def execute(self,args):
            calls.append(args)
            return ToolResult.success('read')
    tool=Read()
    tool._capability_settings=CapabilitySettings(str(tmp_path),user_id='alice')
    tool._capability_settings.set_enabled('tool','read',False)
    assert not is_tool_available(tool)
    assert 'disabled' in permission_denial('read',{},tool=tool).lower()
    with invocation_scope('already-authorized'):
        assert tool.execute_tool({}).status == 'error'
        assert calls == []
        tool._capability_settings.set_enabled('tool','read',True)
        assert tool.execute_tool({}).status == 'success'
        assert calls == [{}]


def test_bound_tool_cannot_read_another_users_setting(tmp_path):
    from common.runtime_identity import identity_scope
    from agent.tools.capability_settings import tool_enabled
    tool=SimpleNamespace(name='read',_capability_settings=CapabilitySettings(str(tmp_path),user_id='alice'))
    with identity_scope(user_id='bob'):
        with pytest.raises(PermissionError):
            tool_enabled('read',tool=tool)
