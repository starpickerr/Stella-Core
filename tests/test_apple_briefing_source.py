import pytest

from application import Application
from agent.briefing.sources.calendar_agenda import CalendarAgendaSource
from agent.briefing.sources import registry

pytestmark = pytest.mark.usefixtures("calendar_plugin_env")


def test_connected_apple_calendar_makes_upcoming_stella_events_available_to_briefing(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    port = Application.port("calendar")
    port.upsert_external_event("apple_calendar", "source-1", {
        "title": "Apple meeting", "description": "Discussion", "location": "Room 2",
        "start_at": "2026-10-10T09:00:00+08:00", "end_at": "2026-10-10T10:00:00+08:00",
        "all_day": False})
    port.create_event({"title": "Stella planning", "start_at": "2026-10-10T11:00:00+08:00",
                       "end_at": "2026-10-10T12:00:00+08:00"})
    source = CalendarAgendaSource(calendar_port=port)
    result = source.fetch({"until": "2026-10-10T00:00:00Z"})
    assert {item.title for item in result.items} == {"Apple meeting", "Stella planning"}
    assert all(item.occurred_at == "2026-10-10T00:00:00Z" for item in result.items)
    assert all("start_at" not in item.payload for item in result.items)
    assert len(port.list_events()) == 2


def test_calendar_source_is_registered_only_when_connected(monkeypatch):
    monkeypatch.setattr(registry, "_email_sources", lambda: [])
    monkeypatch.setattr(registry, "_elearning_sources", lambda: [])
    monkeypatch.setattr(registry, "apple_calendar_connected", lambda: False)
    assert registry.configured_sources() == []
    monkeypatch.setattr(registry, "apple_calendar_connected", lambda: True)
    assert [source.name for source in registry.configured_sources()] == ["calendar_agenda"]


@pytest.mark.parametrize('purpose', ['interactive', 'background'])
def test_native_calendar_collection_uses_managed_owner_grants_and_honors_revocation(tmp_path, monkeypatch, purpose):
    from pathlib import Path
    from types import SimpleNamespace
    from agent.briefing.pipeline import BriefingPipeline
    from core.execution.context import execution_scope
    from core.plugins import management
    from core.plugins.authz import PluginAuthorizationStore
    from core.plugins.first_party_grants import issue_required_grants_for_enabled_plugin
    from core.plugins.management import ManagementStore
    from core.plugins.package_ops import PackageStore
    from core.services import calendar_gateway, calendar_facade

    calendar_gateway.shutdown_calendar_session()
    store = ManagementStore(tmp_path / 'packages')
    packages = PackageStore(store.root)
    root = Path('stella-plugins-workspace/plugins/calendar')
    operation = packages.stage(root)
    packages.inspect(operation.operation_id)
    packages.prepare(operation.operation_id)
    packages.commit(operation.operation_id)
    store.set_intent('stella.calendar', 'local-default', 'enabled')
    monkeypatch.setattr(management, 'default_store', lambda: store)
    authz = PluginAuthorizationStore()
    monkeypatch.setattr(calendar_gateway, 'DEFAULT_AUTHZ', authz)
    monkeypatch.setattr(calendar_facade, '_db_path', lambda: tmp_path / 'calendar.db')
    issue_required_grants_for_enabled_plugin(plugin_id='stella.calendar', user_id='local-default',
        package_root=root, authz=authz)
    port = Application.port('calendar')
    port.create_event({'title': 'Upcoming meeting', 'start_at': '2026-10-10T09:00:00Z',
                       'end_at': '2026-10-10T10:00:00Z'})
    pipeline = BriefingPipeline(service=SimpleNamespace(get_cursor=lambda *args: None), generator=object())
    adapter = CalendarAgendaSource(calendar_port=port)
    def collect():
        with execution_scope(origin='job' if purpose == 'background' else 'ui'):
            return pipeline._fetch_source(adapter, '2026-10-09T00:00:00Z', '2026-10-10T00:00:00Z')
    assert [item.title for item in collect().items] == ['Upcoming meeting']
    ref = f'calendar-default-grant:{purpose}:calendar.read'
    authz.revoke(ref)
    with pytest.raises(PermissionError):
        collect()
    authz.update_owned(ref, user_id='local-default', revision=2, revoked=False)
    assert collect().items
