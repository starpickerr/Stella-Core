"""Tool catalog stays complete without changing what agents receive."""

import json

import pytest

import agent.tools as tools
from agent.tools.catalog import build_catalog, tools_payload
from agent.tools.tool_manager import ToolManager


EXCLUDED = {"BaseTool", "ToolManager", "McpTool"}


def _export_ids():
    ids = []
    for class_name in tools.__all__:
        if class_name in EXCLUDED:
            continue
        ids.append(getattr(tools, class_name).name)
    return ids


def test_catalog_ids_match_exported_adapters_once():
    exported = _export_ids()
    catalog_ids = [item["id"] for item in build_catalog(loaded_ids=set())]
    assert "memory_search" in catalog_ids
    assert "memory_get" in catalog_ids
    assert catalog_ids.count("memory_search") == 1
    assert set(catalog_ids) == set(exported)
    assert len(catalog_ids) == len(set(catalog_ids))
    assert not any(item_id.startswith("mcp") for item_id in catalog_ids)


def test_every_entry_has_bilingual_copy_and_no_secrets():
    for item in build_catalog(loaded_ids={"read"}):
        assert item["id"]
        for field in ("title", "intro", "detail"):
            assert item[field]["zh"].strip()
            assert item[field]["en"].strip()
            assert item[field]["zh"] != item[field]["en"]
        assert "description" not in item
        blob = json.dumps(item, ensure_ascii=False).lower()
        assert "api_key" not in blob
        assert "sk-" not in blob
        assert "token" not in blob


def test_unavailable_tools_stay_listed_with_a_reason():
    rows = {item["id"]: item for item in build_catalog(loaded_ids={"read"})}
    assert rows["read"]["available"] is True
    assert rows["read"]["reason"] is None
    assert rows["web_fetch"]["available"] is False
    assert rows["web_fetch"]["reason"]["zh"]
    assert rows["web_fetch"]["reason"]["en"]
    assert rows["memory_search"]["available"] is False
    assert "记忆" in rows["memory_search"]["reason"]["zh"]
    assert rows["memory_get"]["reason"]["en"]


def test_listing_the_catalog_does_not_register_memory_tools():
    manager = ToolManager()
    manager.load_tools()
    before = set(manager.tool_classes)
    build_catalog(loaded_ids=before)
    assert set(manager.tool_classes) == before
    assert "memory_search" not in manager.tool_classes
    payload = tools_payload()
    assert payload["status"] == "success"
    assert "memory_search" in {item["id"] for item in payload["tools"]}
    again = ToolManager()
    again.load_tools()
    assert "memory_search" not in again.tool_classes


def test_tool_catalog_preserves_actual_implementation_source():
    rows = {row['id']: row for row in build_catalog({'read', 'bills', 'elearning'})}
    assert rows['read']['source'] == {'type': 'builtin', 'plugin_ids': []}
    assert rows['bills']['source'] == {'type': 'plugin', 'plugin_ids': ['stella.bills']}
    assert 'elearning' not in rows  # Supplied only through MCP discovery.
    assert rows['memory_search']['source']['plugin_ids'] == ['stella.memory']
    assert rows['apple']['source']['plugin_ids'] == ['stella.calendar', 'stella.tasks']
    from agent.tools.provenance import tool_source
    for name, owner in [('memory_write','stella.memory'), ('knowledge_write','stella.knowledge')]:
        assert tool_source(name) == {'type':'plugin', 'plugin_ids':[owner]}


@pytest.mark.parametrize('tool_name,plugin_id', [
    ('bills', 'stella.bills'), ('briefing', 'stella.briefing'),
    ('calendar', 'stella.calendar'), ('todos', 'stella.tasks'),
    ('agent_hub', 'stella.agent-hub'),
    ('scheduler', 'stella.automation'), ('memory_search', 'stella.memory'),
    ('memory_get', 'stella.memory'),
])
def test_managed_plugin_switch_hides_catalog_and_cached_calls(tmp_path, monkeypatch, tool_name, plugin_id):
    from agent.tools.base_tool import BaseTool, ToolResult, is_tool_available
    from agent.tools.capability_settings import CapabilitySettings
    from agent.runtime.tool_invocation import invocation_scope
    from core.plugins import management
    from core.plugins.management import ManagementStore

    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    calls = []
    class Adapter(BaseTool):
        name = tool_name
        def execute(self, params):
            calls.append(params)
            return ToolResult.success('ok')
    tool = Adapter()
    tool._capability_settings = CapabilitySettings(str(tmp_path / 'agent'))
    store.set_intent(plugin_id, 'local-default', 'enabled')
    assert is_tool_available(tool)
    if tool_name not in ('memory_search', 'memory_get'):
        assert next(r for r in build_catalog({tool_name}) if r['id']==tool_name)['available']
    for intent in ['disabled', 'removed']:
        store.set_intent(plugin_id, 'local-default', intent)
        assert not is_tool_available(tool)
        assert not next(r for r in build_catalog({tool_name}) if r['id']==tool_name)['available']
        with invocation_scope('catalog-switch-test'):
            assert tool.execute_tool({}).status == 'error'
        assert calls == []
    store.set_intent(plugin_id, 'local-default', 'enabled')
    assert is_tool_available(tool)
    with invocation_scope('catalog-switch-test'):
        assert tool.execute_tool({}).status == 'success'
    assert calls == [{}]


def test_apple_checks_selected_provider_and_plugin_lookup_errors_fail_closed(tmp_path, monkeypatch):
    from agent.tools.provenance import plugin_tool_available
    from core.plugins import management
    from core.plugins.management import ManagementStore
    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    store.set_intent('stella.calendar', 'local-default', 'enabled')
    store.set_intent('stella.tasks', 'local-default', 'disabled')
    assert plugin_tool_available('apple')
    assert plugin_tool_available('apple', {'kind':'calendar'})
    assert not plugin_tool_available('apple', {'kind':'reminders'})
    store.set_intent('stella.calendar', 'local-default', 'disabled')
    assert not plugin_tool_available('apple')
    def broken():
        raise OSError('state unavailable')
    monkeypatch.setattr(management, 'default_store', broken)
    assert not plugin_tool_available('bills')
    assert plugin_tool_available('read')  # A plugin failure does not remove core file reads.


def test_legacy_scheduler_keeps_its_actual_core_route_when_automation_is_off(tmp_path, monkeypatch):
    from agent.scheduler import TaskStore
    from agent.tools.scheduler.scheduler_tool import SchedulerTool
    from agent.tools.base_tool import is_tool_available
    from agent.tools.capability_settings import CapabilitySettings
    from agent.runtime.tool_invocation import invocation_scope
    from core.plugins import management
    from core.plugins.management import ManagementStore

    store = ManagementStore(tmp_path / 'packages')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    store.set_intent('stella.automation', 'local-default', 'disabled')
    tool = SchedulerTool()
    tool.task_store = TaskStore(str(tmp_path / 'legacy-tasks.json'))
    tool._capability_settings = CapabilitySettings(str(tmp_path / 'agent'))
    from agent.tools.provenance import tool_source
    assert tool_source(tool.name, tool) == {'type':'builtin', 'plugin_ids':[]}
    assert is_tool_available(tool)
    with invocation_scope('legacy-scheduler'):
        result = tool.execute_tool({'action':'list'})
    assert result.status == 'success' and '暂无定时任务' in result.result

    from agent.scheduler.automation_store import AutomationStore
    tool.task_store = AutomationStore(tmp_path / 'automation-tasks.json', 'default')
    assert tool_source(tool.name, tool)['plugin_ids'] == ['stella.automation']
    assert not is_tool_available(tool)
    with invocation_scope('managed-scheduler'):
        assert tool.execute_tool({'action':'list'}).status == 'error'
