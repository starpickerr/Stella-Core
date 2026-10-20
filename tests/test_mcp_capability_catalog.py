"""The UI reads runtime inventory without opening connections or exposing config."""
import json
from types import SimpleNamespace

from agent.tools.tool_manager import ToolManager


def test_mcp_catalog_reports_runtime_tools_and_pending_servers():
    manager = object.__new__(ToolManager)
    manager.__init__()
    manager._mcp_active_configs = {
        'docs': {'name': 'docs', 'type': 'streamable-http', 'url': 'https://secret/token', 'headers': {'Authorization': 'secret'}},
        'offline': {'name': 'offline', 'type': 'stdio', 'env': {'API_KEY': 'secret'}},
        'booting': {'name': 'booting', 'type': 'stdio'},
    }
    manager._mcp_status = {'docs': 'ready', 'offline': 'failed', 'booting': 'pending'}
    manager._mcp_tool_instances = {'internal_id': SimpleNamespace(
        server_name='docs', remote_name='search', description='Search documents')}
    result = manager.mcp_catalog()
    assert result == [
        {'name': 'booting', 'transport': 'stdio', 'state': 'pending', 'tools': []},
        {'name': 'docs', 'transport': 'streamable-http', 'state': 'ready',
         'tools': [{'name': 'search', 'description': 'Search documents'}]},
        {'name': 'offline', 'transport': 'stdio', 'state': 'failed', 'tools': []},
    ]
    assert 'secret' not in json.dumps(result)


def test_unstarted_configured_server_is_not_reported_as_available(monkeypatch):
    manager = object.__new__(ToolManager)
    manager.__init__()
    manager._mcp_active_configs = {}
    manager._mcp_status = {}
    manager._mcp_tool_instances = {}
    monkeypatch.setattr(manager, '_load_mcp_configs', lambda: [{'name': 'local', 'type': 'stdio'}])
    assert manager.mcp_catalog() == [
        {'name': 'local', 'transport': 'stdio', 'state': 'not_started', 'tools': []}]


def test_catalog_uses_published_tools_without_requerying_the_server(monkeypatch):
    import sys
    from pathlib import Path

    manager = object.__new__(ToolManager)
    manager.__init__()
    from agent.tools.mcp import mcp_client
    monkeypatch.setattr(mcp_client, '_reload_callback', mcp_client._reload_callback)
    configs = [{'name': 'catalog-echo', 'type': 'stdio', 'command': sys.executable,
                'args': [str(Path('tests/fixtures/mcp_echo_server.py').resolve())]}]
    manager._mcp_active_configs = {cfg['name']: cfg for cfg in configs}
    manager._load_mcp_tools_async(configs)
    try:
        assert manager.list_mcp_status() == {'catalog-echo': 'ready'}
        client = manager._mcp_registry.get('catalog-echo')

        def unexpected_network_call():
            raise AssertionError('Inventory must not send tools/list requests')

        monkeypatch.setattr(client, 'list_tools', unexpected_network_call)
        rows = manager.mcp_catalog()
        assert rows[0]['state'] == 'ready'
        assert [tool['name'] for tool in rows[0]['tools']] == ['echo']
        assert rows[0]['tools'][0]['description']
    finally:
        if manager._mcp_registry:
            with manager._mcp_registry._registry_lock:
                client = manager._mcp_registry._clients.pop('catalog-echo', None)
            if client:
                client.shutdown()


def test_mcp_http_handler_checks_auth_before_reading_catalog(monkeypatch):
    import pytest
    from channel.desktop import desktop_channel

    def deny():
        raise PermissionError('Authentication required')

    monkeypatch.setattr(desktop_channel, '_require_auth', deny)
    with pytest.raises(PermissionError, match='Authentication required'):
        desktop_channel.McpCatalogHandler().GET()
