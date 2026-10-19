from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.services import calendar_gateway
from core.services.calendar_facade import CalendarPluginFacade

PLUGIN_ROOT = Path("stella-plugins-workspace/plugins/calendar")


@pytest.fixture(autouse=True)
def _plugin_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_CALENDAR_PLUGIN", "1")
    monkeypatch.setenv("STELLA_CALENDAR_PLUGIN_ROOT", str(PLUGIN_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    monkeypatch.setattr(
        "core.services.calendar_facade._db_path", lambda: tmp_path / "calendar.db"
    )
    yield
    calendar_gateway.shutdown_calendar_session()


EVENT = {
    "title": "站会",
    "start_at": "2026-08-03T09:00:00+08:00",
    "end_at": "2026-08-03T09:30:00+08:00",
}


def test_gateway_create_and_list(tmp_path):
    db = tmp_path / "direct.db"
    created = calendar_gateway.invoke_calendar(
        "create_event", {**EVENT, "idempotencyKey": "op-1"}, db_path=db
    )
    assert created["status"] == "succeeded"
    assert created["value"]["title"] == "站会"
    listed = calendar_gateway.invoke_calendar(
        "list_events",
        {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-31T00:00:00+08:00"},
        db_path=db,
    )
    assert [e["id"] for e in listed["value"]] == [created["value"]["id"]]


def test_plugin_package_has_no_agent_imports():
    for path in PLUGIN_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith(("agent", "common", "core")), (path, name)
    assert not (PLUGIN_ROOT / "backend/domain/apple_sync.py").exists()
    assert (PLUGIN_ROOT / "backend/domain/schema.sql").is_file()


def test_facade_categories_and_events():
    cal = CalendarPluginFacade()
    cats = cal.categories()
    assert "personal" in {c["id"] for c in cats}
    cat = cal.create_category({"name": "运动", "color": "#112233"})
    assert cal.get_category(cat["id"])["name"] == "运动"
    assert cal.update_category(cat["id"], {"color": "#445566"})["color"] == "#445566"
    event = cal.create_event({**EVENT, "category_id": cat["id"]})
    assert cal.get_event(event["id"])["category_id"] == cat["id"]
    moved = cal.set_event_category(event["id"], "work")
    assert moved["category_id"] == "work"
    updated = cal.update_event(event["id"], {"title": "晨会"})
    assert updated["title"] == "晨会" and updated["user_modified"] == 1
    assert cal.delete_category(cat["id"]) is None
    assert cal.delete_event(event["id"]) is None
    with pytest.raises(KeyError):
        cal.get_event(event["id"])


def test_facade_validation_errors_map_to_value_error():
    cal = CalendarPluginFacade()
    with pytest.raises(ValueError, match="end_at must be after start_at"):
        cal.create_event({**EVENT, "end_at": EVENT["start_at"]})
    with pytest.raises(KeyError):
        cal.get_category("missing")


def test_facade_recurrence_and_exclusion():
    cal = CalendarPluginFacade()
    series = cal.create_event(
        {**EVENT, "repeat_frequency": "daily", "repeat_timezone": "Asia/Shanghai"}
    )
    window = ("2026-08-03T00:00:00+08:00", "2026-08-06T00:00:00+08:00")
    assert len(cal.list_events(*window)) == 3
    assert cal.exclude_occurrence(series["id"], "2026-08-04") is None
    assert len(cal.list_events(*window)) == 2


def test_facade_imports_and_special_dates():
    cal = CalendarPluginFacade()
    result = cal.import_china_holidays(2026)
    assert result["added"] == result["total"] > 0
    assert cal.import_china_holidays(2026)["added"] == 0
    special = cal.create_special_date({"title": "生日", "date": "2026-09-09", "annual": True})
    assert special["source_type"] == "special_date"
    csv = "title,date,annual\n纪念日,2026-10-10,true\n"
    assert cal.import_special_dates(csv, "csv", "Asia/Shanghai") == {"added": 1, "total": 1}
    with pytest.raises(ValueError):
        cal.import_china_holidays(2030)


def test_facade_external_event_and_briefing_surface():
    cal = CalendarPluginFacade()
    ext = cal.upsert_external_event("apple_calendar", "ek:1", EVENT)
    assert ext["source_type"] == "apple_calendar"
    again = cal.upsert_external_event(
        "apple_calendar", "ek:1", {**EVENT, "title": "改名"}, event_id=ext["id"]
    )
    assert again["id"] == ext["id"] and again["title"] == "改名"

    briefed = cal.create_event(EVENT, _briefing_key="b:1")
    assert briefed["source_type"] == "briefing"
    detail = {"briefing": {"id": "brief-1"}}
    assert cal.ingest_briefing_revision(detail, 1) == 0
    cal.delete_event(briefed["id"])
    assert cal.has_source_tombstone(["b:1", None]) is True
    assert cal.has_source_tombstone(["b:none"]) is False


def test_application_port_routes_to_plugin(monkeypatch):
    from application.api import Application

    port = Application.port("calendar")
    assert type(port._service).__name__ == "CalendarPluginFacade"
    event = port.create_event(EVENT)
    assert port.get_event(event["id"])["title"] == "站会"


def test_application_port_defaults_to_core_service(monkeypatch, tmp_path):
    monkeypatch.delenv("STELLA_CALENDAR_PLUGIN")
    monkeypatch.setenv("STELLA_DATA_DIR", str(tmp_path))
    from application.api import Application

    port = Application.port("calendar")
    assert type(port._service).__name__ == "CalendarService"


def test_default_plugins_and_catalog_list_calendar():
    import hashlib
    import json

    from core.plugins.distribution import load_default_plugin_manifest

    ids = {row["pluginId"] for row in load_default_plugin_manifest()["plugins"]}
    assert "stella.calendar" in ids

    catalog = json.loads(
        (Path("..") / "Stella-Plugins" / "catalog" / "official.json").read_text(encoding="utf-8")
    ) if (Path("..") / "Stella-Plugins" / "catalog" / "official.json").is_file() else None
    if catalog is None:
        pytest.skip("Stella-Plugins sibling checkout not present")
    entry = next(p for p in catalog["plugins"] if p["pluginId"] == "stella.calendar")
    h = hashlib.sha256()
    root = PLUGIN_ROOT.resolve()
    for f in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(f.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    assert h.hexdigest() == entry["sha256"]
