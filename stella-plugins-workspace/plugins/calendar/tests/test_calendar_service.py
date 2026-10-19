"""Calendar domain regressions, owned and executed by the Calendar plugin."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import pytest
from stella_calendar_domain.service import CalendarService

@pytest.fixture
def service(tmp_path):
    return CalendarService(tmp_path / 'calendar.db')

def test_events_categories_and_time_ranges_persist(service):
    group = service.create_category({"name": "旅行", "color": "#123ABC"})
    event = service.create_event({
        "title": "出发", "start_at": "2026-10-01T09:00:00+08:00",
        "end_at": "2026-10-01T10:00:00+08:00", "category_id": group["id"],
    })
    assert event["start_at"] == "2026-10-01T01:00:00+00:00"
    assert [row["id"] for row in CalendarService(service.db_path).list_events(
        "2026-10-01T00:00:00+08:00", "2026-10-02T00:00:00+08:00", group["id"])] == [event["id"]]
    changed = service.update_event(event["id"], {"title": "乘车", "location": "车站"})
    assert changed["title"] == "乘车" and changed["user_modified"] == 1
    service.delete_category(group["id"])
    assert service.get_event(event["id"])["category_id"] is None
    service.delete_event(event["id"])
    assert service.list_events() == []
    with pytest.raises(ValueError):
        service.create_event({"title": "bad", "start_at": "2026-10-01T10:00+08:00", "end_at": "2026-10-01T09:00+08:00"})

def test_default_categories_are_for_schedules(service):
    assert [category["id"] for category in service.categories()] == [
        "personal", "work", "study", "china_holidays"]
    with pytest.raises(ValueError):
        service.delete_category("china_holidays")

def test_weekly_series_expands_selected_days_and_updates_whole_series(service):
    event = service.create_event({
        "title": "上课", "start_at": "2026-10-05T09:00+08:00", "end_at": "2026-10-05T10:00+08:00",
        "repeat_frequency": "weekly", "repeat_days": [0, 2], "repeat_until": "2026-10-14",
        "repeat_timezone": "Asia/Shanghai",
    })
    rows = service.list_events("2026-10-05T00:00+08:00", "2026-10-19T00:00+08:00")
    assert [row["start_at"] for row in rows] == [
        "2026-10-05T01:00:00+00:00", "2026-10-07T01:00:00+00:00",
        "2026-10-12T01:00:00+00:00", "2026-10-14T01:00:00+00:00",
    ]
    assert all(row["series_id"] == event["id"] for row in rows)
    service.update_event(event["id"], {"title": "新课程"})
    assert all(row["title"] == "新课程" for row in service.list_events("2026-10-05T00:00+08:00", "2026-10-19T00:00+08:00"))

def test_daily_recurrence_preserves_local_time_across_dst(service):
    service.create_event({"title": "晨会", "start_at": "2026-10-31T09:00-04:00",
        "end_at": "2026-10-31T10:00-04:00", "repeat_frequency": "daily",
        "repeat_timezone": "America/New_York", "repeat_until": "2026-11-02"})
    rows = service.list_events("2026-10-31T00:00-04:00", "2026-11-03T00:00-05:00")
    assert [row["start_at"] for row in rows] == [
        "2026-10-31T13:00:00+00:00", "2026-11-01T14:00:00+00:00", "2026-11-02T14:00:00+00:00"]

def test_monthly_and_yearly_recurrence_skip_missing_calendar_dates(service):
    service.create_event({"title": "月末", "start_at": "2026-01-31T09:00+08:00",
        "end_at": "2026-01-31T10:00+08:00", "repeat_frequency": "monthly",
        "repeat_timezone": "Asia/Shanghai"})
    service.create_event({"title": "闰日", "start_at": "2024-02-29T09:00+08:00",
        "end_at": "2024-02-29T10:00+08:00", "repeat_frequency": "yearly",
        "repeat_timezone": "Asia/Shanghai"})
    assert [row["title"] for row in service.list_events("2026-02-01T00:00+08:00", "2026-03-01T00:00+08:00")] == []
    assert [row["title"] for row in service.list_events("2026-03-01T00:00+08:00", "2026-04-01T00:00+08:00")] == ["月末"]

def test_existing_database_gets_recurrence_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE calendar_events (id TEXT PRIMARY KEY, title TEXT, description TEXT,
            start_at TEXT, end_at TEXT, all_day INTEGER, location TEXT, category_id TEXT,
            source_type TEXT, source_key TEXT, source_url TEXT, user_modified INTEGER,
            created_at TEXT, updated_at TEXT)""")
    service = CalendarService(path)
    event = service.create_event({"title": "迁移后", "start_at": "2026-10-01T09:00+08:00", "end_at": "2026-10-01T10:00+08:00"})
    assert event["repeat_frequency"] == "none"

def test_concurrent_calendar_requests_migrate_old_database_once(tmp_path):
    path = tmp_path / "old-concurrent.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE calendar_events (id TEXT PRIMARY KEY, title TEXT, description TEXT,
            start_at TEXT, end_at TEXT, all_day INTEGER, location TEXT, category_id TEXT,
            source_type TEXT, source_key TEXT, source_url TEXT, user_modified INTEGER,
            created_at TEXT, updated_at TEXT)""")
    ready = Barrier(8)
    def open_calendar(_):
        ready.wait()
        return CalendarService(path).categories()
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert len(list(pool.map(open_calendar, range(8)))) == 8
    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(calendar_events)")]
    assert columns.count("repeat_frequency") == 1

def test_official_holidays_import_into_current_calendar_once(service):
    result = service.import_china_holidays(2026)
    assert result == {"year": 2026, "added": 13, "total": 13}
    assert service.import_china_holidays(2026)["added"] == 0
    rows = service.list_events("2026-09-25T00:00+08:00", "2026-09-28T00:00+08:00")
    assert len(rows) == 1 and rows[0]["title"] == "中秋节（休）"
    assert rows[0]["source_type"] == "china_holiday"
    assert rows[0]["category_id"] == "china_holidays"
    assert rows[0]["source_url"].startswith("https://www.gov.cn/")
    assert service.list_events("2026-10-10T00:00+08:00", "2026-10-11T00:00+08:00")[0]["title"] == "调休上班（班）"
    with pytest.raises(ValueError, match="cannot be edited"):
        service.update_event(rows[0]["id"], {"title": "changed"})
    assert len([row for row in service.list_events() if row["source_type"] == "china_holiday"]) == 13

def test_manual_and_file_special_dates_share_calendar_and_recur(service):
    manual = service.create_special_date({"title": "生日", "date": "2026-10-01", "annual": True,
                                          "timezone": "Asia/Shanghai", "description": "家人"})
    assert manual["source_type"] == "special_date" and manual["all_day"] == 1
    assert manual["category_id"] == "personal"
    assert service.list_events("2027-10-01T00:00+08:00", "2027-10-02T00:00+08:00")[0]["title"] == "生日"
    csv_content = "title,date,annual,description\n考试,2026-10-02,false,重要\n"
    assert service.import_special_dates(csv_content, "csv", "Asia/Shanghai") == {"added": 1, "total": 1}
    assert service.import_special_dates(csv_content, "csv", "Asia/Shanghai")["added"] == 0
    ics_content = "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:anniversary-1\nSUMMARY:纪念日\nDTSTART;VALUE=DATE:20261003\nRRULE:FREQ=YEARLY\nEND:VEVENT\nEND:VCALENDAR"
    assert service.import_special_dates(ics_content, "ics", "Asia/Shanghai") == {"added": 1, "total": 1}
    assert service.import_special_dates(ics_content, "ics", "Asia/Shanghai")["added"] == 0
    assert {row["title"] for row in service.list_events()} == {"生日", "考试", "纪念日"}
    assert [row["id"] for row in service.categories()] == ["personal", "work", "study", "china_holidays"]
    assert service.list_events("2027-10-03T00:00+08:00", "2027-10-04T00:00+08:00")[0]["title"] == "纪念日"

def test_old_special_date_category_merges_into_personal_without_losing_events(service):
    row = service.create_special_date({"title": "旧纪念日", "date": "2026-10-01", "annual": False})
    with sqlite3.connect(service.db_path) as db:
        db.execute("INSERT INTO calendar_categories VALUES (?,?,?,?)", ("special_dates", "特殊日期", "#D183C6", "2026-01-01"))
        db.execute("UPDATE calendar_events SET category_id='special_dates' WHERE id=?", (row["id"],))
    reopened = CalendarService(service.db_path)
    assert reopened.get_event(row["id"])["category_id"] == "personal"
    assert "special_dates" not in {category["id"] for category in reopened.categories()}

def test_bad_special_date_file_does_not_partially_import(service):
    with pytest.raises(ValueError):
        service.import_special_dates("title,date\n有效,2026-10-02\n无效,2026-02-30\n", "csv", "Asia/Shanghai")
    assert service.list_events() == []

def test_briefing_handoff_is_idempotent_and_preserves_user_edits(service):
    item = SimpleNamespace(source="elearning", account_id="student", source_id="quiz-1",
        source_item_id="src-1", section="action", title="课程测验", snippet="周五截止",
        payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="https://example.test/quiz",
        id="item-1")
    detail = {"briefing": SimpleNamespace(id="briefing-1"), "items": [item], "mail": [
        {"id": "src-1", "decision": {"calendar": {"start_at": "2026-10-02T09:00:00+08:00"}}}]}
    assert service.ingest_briefing(detail) == 0
    assert service.list_events() == []
    key = json.dumps([item.source, item.account_id, item.source_id], separators=(',', ':'))
    service._upsert_sourced_event(key, item, '2026-10-02T09:00:00+08:00', '2026-10-02T10:00:00+08:00', False)
    service._upsert_sourced_event(key, item, '2026-10-02T09:00:00+08:00', '2026-10-02T10:00:00+08:00', False)
    assert len(service.list_events()) == 1
    event = service.list_events()[0]
    assert event["category_id"] == "study"
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT destination FROM agenda_handoffs ORDER BY destination").fetchall() == []
    service.update_event(event["id"], {"title": "我修改的标题"})
    item.title = "来源的新标题"
    service.ingest_briefing(detail)
    service._upsert_sourced_event(key, item, '2026-10-02T09:00:00+08:00', '2026-10-02T10:00:00+08:00', False)
    assert service.get_event(event["id"])["title"] == "我修改的标题"

def test_briefing_reclassification_preserves_existing_business_object(service):
    item = SimpleNamespace(source="elearning", account_id="student", source_id="quiz-2",
        source_item_id="src-2", section="action", title="旧截止", snippet="截止",
        payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="", id="item-2")
    detail = {"briefing": SimpleNamespace(id="briefing-2"), "items": [item], "mail": []}
    service.ingest_briefing(detail)
    assert service.list_events() == []
    key = json.dumps([item.source, item.account_id, item.source_id], separators=(',', ':'))
    event = service._upsert_sourced_event(key, item, '2026-10-02T09:00:00+08:00', '2026-10-02T10:00:00+08:00', False)
    item.section = "fyi"
    item.payload = {}
    service.ingest_briefing(detail)
    assert len(service.list_events()) == 1
    assert service.get_event(event['id'])['title'] == '旧截止'
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT count(*) FROM agenda_handoffs").fetchone()[0] == 0

def test_deleted_default_category_does_not_block_briefing_import(service):
    service.delete_category("study")
    assert "study" not in {row["id"] for row in CalendarService(service.db_path).categories()}
    item = SimpleNamespace(source="elearning", account_id="student", source_id="quiz-3",
        source_item_id="src-3", thread_id="", section="action", title="新截止", snippet="截止",
        payload={"due_at": "2026-10-02T20:00:00+08:00"}, url="", id="item-3")
    service.ingest_briefing({"briefing": SimpleNamespace(id="briefing-4"), "items": [item], "mail": [
        {"id": "src-3", "decision": {"calendar": {"start_at": "2026-10-02T09:00:00+08:00"}}}]})
    assert service.list_events() == []
    key = json.dumps([item.source, item.account_id, item.source_id], separators=(',', ':'))
    service._upsert_sourced_event(key, item, '2026-10-02T09:00:00+08:00', '2026-10-02T10:00:00+08:00', False)
    assert service.list_events()[0]["category_id"] is None

def test_merged_briefing_thread_routes_each_selected_source(service):
    card = SimpleNamespace(source="email", account_id="inbox", source_id="first",
        source_item_id="src-1", thread_id="thread-1", section="action",
        title="会议通知", snippet="摘要", payload={}, url="", id="card-1")
    mail = [
        {"id": "src-1", "source": "email", "account_id": "inbox", "source_id": "first",
         "thread_id": "thread-1", "category": "selected", "decision": {"section": "action"}},
        {"id": "src-2", "source": "email", "account_id": "inbox", "source_id": "second",
         "thread_id": "thread-1", "category": "selected", "title": "会议改期", "snippet": "摘要",
         "metadata": {}, "url": "", "decision": {"section": "action", "calendar": {
             "start_at": "2026-10-03T10:00:00+08:00"}}},
    ]
    assert service.ingest_briefing({"briefing": SimpleNamespace(id="briefing-3"), "items": [card], "mail": mail}) == 0
    assert service.list_events() == []
    with sqlite3.connect(service.db_path) as db:
        assert db.execute("SELECT count(*) FROM agenda_handoffs WHERE destination='task'").fetchone()[0] == 0

