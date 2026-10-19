"""Management HTTP uses the trusted caller; paths/identities are not inputs."""
import json
from types import SimpleNamespace

from channel.desktop import desktop_channel as channel


def test_http_management_requires_auth_and_does_not_accept_data_handles(monkeypatch):
    authenticated = []
    monkeypatch.setattr(channel, '_require_auth', lambda: authenticated.append(True))
    monkeypatch.setattr(channel.web, 'header', lambda *args: None)
    monkeypatch.setattr(channel.web, 'data', lambda: json.dumps({'action': 'install', 'pluginId': 'stella.bills',
                                                               'dataHandle': '/untrusted'}).encode())
    result = json.loads(channel.PluginManagementHandler().POST())
    assert authenticated
    assert result['status'] == 'error'
    assert 'dataHandle' in result['message']


def test_http_settings_conflict_is_reported_without_false_success(monkeypatch):
    from core.plugins.management import RevisionConflict
    monkeypatch.setattr(channel, '_require_auth', lambda: None)
    monkeypatch.setattr(channel.web, 'header', lambda *args: None)
    monkeypatch.setattr(channel.web, 'data', lambda: json.dumps({'action': 'save', 'pluginId': 'stella.sample',
        'settingsId': 'preferences', 'category': 'general', 'expectedRevision': 1, 'changes': {'notes': 'draft'}}).encode())

    def conflict(*args, **kwargs):
        raise RevisionConflict('reload and merge retained draft')

    monkeypatch.setattr(channel, '_plugin_settings_service', lambda: SimpleNamespace(save=conflict))
    result = json.loads(channel.PluginSettingsHandler().POST())
    assert result['status'] == 'conflict'
