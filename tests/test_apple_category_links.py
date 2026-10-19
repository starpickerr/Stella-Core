import pytest

from agent.apple.category_links import reconcile_names, validate_links
from agent.calendar.apple_sync import AppleCalendarSync
from application import Application
from tests.test_apple_calendar_sync import FakeBridge, remote_event
from tests.test_apple_reminder_sync import manager as reminder_manager
from tests.test_apple_reminder_sync import reminder

pytestmark = pytest.mark.usefixtures("calendar_plugin_env")


def test_name_sync_is_independent_of_content_direction():
    assert reconcile_names("课程", "课程", "大学课程", "课程") == ("apple_to_stella", "大学课程")
    assert reconcile_names("课程", "课程", "课程", "大学课程") == ("stella_to_apple", "大学课程")
    assert reconcile_names("课程", "课程", "大学课程", "学期课") == ("conflict", None)
    assert reconcile_names("课程", "课程", "大学课程", "大学课程") == ("aligned", "大学课程")
    assert reconcile_names("课程", "课程", "课程", "课程") == ("unchanged", "课程")


def test_links_are_one_to_one():
    validate_links([
        {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": True},
    ])
    with pytest.raises(ValueError, match="one-to-one"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": True},
            {"apple_id": "cal-b", "stella_id": "study", "direction": "export", "enabled": True},
        ])
    with pytest.raises(ValueError, match="one-to-one"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": True},
            {"apple_id": "cal-a", "stella_id": "work", "direction": "export", "enabled": True},
        ])


def test_replacing_calendar_links_unlinks_without_deleting_events(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    bridge = FakeBridge([
        remote_event("course", "lecture", "Lecture"),
        remote_event("personal", "dinner", "Dinner"),
    ])
    bridge.available = {"course", "personal"}
    port = Application.port("calendar")
    personal = next(row for row in port.categories() if row["id"] == "personal")
    sync = AppleCalendarSync(
        bridge=bridge, db_path=tmp_path / "sync.db", calendar_port=port,
        clock=lambda: "2026-10-10T00:00:00+00:00",
    )
    saved = sync.replace_links([
        {"apple_id": "course", "create_name": "课程", "direction": "import", "enabled": True},
        {"apple_id": "personal", "stella_id": personal["id"], "direction": "export", "enabled": True},
    ])
    course = next(row for row in saved["links"] if row["apple_id"] == "course")
    dinner = port.create_event({
        "title": "晚饭", "start_at": "2026-10-12T10:00:00Z", "end_at": "2026-10-12T11:00:00Z",
        "category_id": personal["id"],
    })
    again = sync.replace_links([
        {"apple_id": "course", "create_name": "课程", "direction": "import", "enabled": True},
    ])
    assert [row["apple_id"] for row in again["links"]] == ["course"]
    assert again["links"][0]["stella_id"] == course["stella_id"]
    assert port.get_event(dinner["id"])["title"] == "晚饭"
    assert again["connected"] is True


def _linked_calendar(tmp_path, monkeypatch, rows, available):
    monkeypatch.setattr("common.state_dir.calendar_db", lambda **_kwargs: tmp_path / "calendar.db")
    bridge = FakeBridge(rows)
    bridge.available = set(available)
    port = Application.port("calendar")
    sync = AppleCalendarSync(
        bridge=bridge, db_path=tmp_path / "sync.db", calendar_port=port,
        clock=lambda: "2026-10-10T00:00:00+00:00",
    )
    return sync, bridge, port


def test_enabled_calendar_names_sync_both_ways_and_conflicts_do_not_overwrite(tmp_path, monkeypatch):
    sync, bridge, port = _linked_calendar(
        tmp_path, monkeypatch, [remote_event("course", "lecture", "Lecture")], {"course", "notes"})
    saved = sync.replace_links([
        {"apple_id": "course", "create_name": "课程", "direction": "import", "enabled": True},
        {"apple_id": "notes", "create_name": "笔记", "direction": "import", "enabled": False},
    ])
    course = next(row for row in saved["links"] if row["apple_id"] == "course")
    notes = next(row for row in saved["links"] if row["apple_id"] == "notes")
    bridge.titles["course"] = "大学课程"
    result = sync.sync(manual=True)
    assert result["status"] == "success"
    assert port.get_category(course["stella_id"])["name"] == "大学课程"
    assert sync.status()["links"][0]["stella_id"] == course["stella_id"]
    assert sync.status()["links"][0]["direction"] == "import"

    port.update_category(course["stella_id"], {"name": "学期课"})
    sync.sync(manual=True)
    assert ("rename", "course", "学期课") in bridge.writes

    port.update_category(notes["stella_id"], {"name": "课堂笔记"})
    bridge.writes.clear()
    sync.sync(manual=True)
    assert all(item[1] != "notes" for item in bridge.writes if item[0] == "rename")

    bridge.titles["course"] = "另一边"
    # Stored snapshot is 学期课 after the previous Stella rename. Change Stella again.
    port.update_category(course["stella_id"], {"name": "本地课"})
    sync.sync(manual=True)
    link = next(row for row in sync.status()["links"] if row["apple_id"] == "course")
    assert link["name_conflict"]
    assert port.get_category(course["stella_id"])["name"] == "本地课"
    assert bridge.titles["course"] == "另一边"


def test_read_only_calendar_rename_keeps_stella_and_fails_the_sync(tmp_path, monkeypatch):
    sync, bridge, port = _linked_calendar(
        tmp_path, monkeypatch, [remote_event("course", "lecture", "Lecture")], {"course"})
    saved = sync.replace_links([
        {"apple_id": "course", "create_name": "课程", "direction": "import", "enabled": True},
    ])
    course_id = saved["links"][0]["stella_id"]
    bridge.read_only.add("course")
    port.update_category(course_id, {"name": "大学课程"})
    result = sync.sync(manual=True)
    assert result["status"] != "success"
    assert port.get_category(course_id)["name"] == "大学课程"
    assert "Calendar is read only" in sync.status()["links"][0]["name_conflict"]


def test_content_follows_each_link_and_unlinking_stops_updates(tmp_path, monkeypatch):
    sync, bridge, port = _linked_calendar(tmp_path, monkeypatch, [
        remote_event("course", "lecture", "Lecture"),
        remote_event("personal", "dinner", "Dinner"),
        remote_event("shared", "meeting", "Meeting"),
    ], {"course", "personal", "shared"})
    personal = next(row for row in port.categories() if row["id"] == "personal")
    work = next(row for row in port.categories() if row["id"] == "work")
    study = next(row for row in port.categories() if row["id"] == "study")
    sync.replace_links([
        {"apple_id": "course", "create_name": "课程", "direction": "import", "enabled": True},
        {"apple_id": "personal", "stella_id": personal["id"], "direction": "export", "enabled": True},
        {"apple_id": "shared", "stella_id": work["id"], "direction": "bidirectional", "enabled": True},
    ])
    course_id = next(row["stella_id"] for row in sync.status()["links"] if row["apple_id"] == "course")
    port.create_event({
        "title": "健身", "start_at": "2026-10-12T10:00:00Z", "end_at": "2026-10-12T11:00:00Z",
        "category_id": personal["id"],
    })
    port.create_event({
        "title": "读书", "start_at": "2026-10-12T12:00:00Z", "end_at": "2026-10-12T13:00:00Z",
        "category_id": study["id"],
    })
    sync.sync(manual=True)
    lecture = next(row for row in port.list_events() if row["title"] == "Lecture")
    assert lecture["category_id"] == course_id
    assert not any(row["title"] == "Dinner" for row in port.list_events())
    meeting = next(row for row in port.list_events() if row["title"] == "Meeting")
    assert meeting["category_id"] == work["id"]
    exported = [row["title"] for row in bridge.upsert_requests]
    assert "健身" in exported
    assert "读书" not in exported
    assert all(row["calendar_id"] != "course" for row in bridge.upsert_requests)

    sync.replace_links([
        {"apple_id": "personal", "stella_id": personal["id"], "direction": "export", "enabled": True},
    ])
    bridge.rows[0]["title"] = "改过的课"
    sync.sync(manual=True)
    assert next(row for row in port.list_events() if row["id"] == lecture["id"])["title"] == "Lecture"


def test_calendar_batch_transfer_uses_category_and_range_without_connecting(tmp_path, monkeypatch):
    sync, _bridge, port = _linked_calendar(
        tmp_path, monkeypatch,
        [remote_event("course", "lecture", "Lecture"),
         remote_event("course", "later", "Later", start_at="2027-03-01T01:00:00Z", end_at="2027-03-01T02:00:00Z")],
        {"course"})
    created = port.create_category({"name": "课程"})
    preview = sync.preview_batch("import", [{"apple_id": "course", "stella_id": created["id"]}],
                                 "2026-09-01", "2027-01-31")
    assert preview["preview"] == {"new": 1, "skipped": 0, "failed": 0}
    result = sync.transfer_batch("import", [{"apple_id": "course", "stella_id": created["id"]}],
                                 "2026-09-01", "2027-01-31", preview["preview_token"], confirm=True)
    assert result["imported"] == 1
    imported = next(row for row in port.list_events() if row["title"] == "Lecture")
    assert imported["category_id"] == created["id"]
    assert sync.status()["connected"] is False
    assert sync.status()["links"] == []
    again = sync.preview_batch("import", [{"apple_id": "course", "stella_id": created["id"]}],
                               "2026-09-01", "2027-01-31")
    assert again["preview"]["new"] == 0
    assert again["preview"]["skipped"] == 1


@pytest.mark.usefixtures("todos_plugin")
def test_reminder_links_sync_names_without_clearing_stella_fields(tmp_path):
    sync, todos, bridge, _clock = reminder_manager(tmp_path, [reminder("hw", "study", "作业")])
    bridge.available = {"study", "home"}
    saved = sync.replace_links([
        {"apple_id": "study", "create_name": "学习", "direction": "import", "enabled": True},
        {"apple_id": "home", "create_name": "生活", "direction": "export", "enabled": True},
    ])
    study_id = next(row["stella_id"] for row in saved["links"] if row["apple_id"] == "study")
    home_id = next(row["stella_id"] for row in saved["links"] if row["apple_id"] == "home")
    sync.sync(manual=True)
    imported = next(row for row in todos.list_todos() if row["title"] == "作业")
    assert imported["category_id"] == study_id
    assert imported["list_name"] == "学习"
    child = todos.add_subtask(imported["id"], {"title": "子任务"})
    other = todos.create_todo({"title": "前置"})
    todos.add_dependency(imported["id"], other["id"])
    todos.change_todo_status(other["id"], "completed")
    todos.change_todo_status(imported["id"], "in_progress")
    bridge.rows[0]["notes"] = "updated note"
    sync.sync(manual=True)
    imported = todos.get_todo(imported["id"])
    assert imported["status"] == "in_progress"
    assert todos.get_todo(child["id"])["parent_id"] == imported["id"]
    assert imported["dependency_ids"] == [other["id"]]
    todos.update_category(study_id, {"name": "大学学习"})
    sync.sync(manual=True)
    assert ("reminder_rename", "study", "大学学习") in bridge.writes
    local = todos.set_todo_category(todos.create_todo({
        "title": "买菜", "due_on": "2026-10-12", "timezone": "Asia/Shanghai",
    })["id"], home_id)
    todos.create_todo({"title": "不导出", "due_on": "2026-10-12", "timezone": "Asia/Shanghai"})
    bridge.rows.append(reminder("dinner", "home", "晚饭"))
    bridge.writes.clear()
    sync.sync(manual=True)
    assert not any(row["title"] == "晚饭" for row in todos.list_todos())
    assert any(row.get("title") == "买菜" and row.get("list_id") == "home" for row in bridge.writes)
    assert all(row.get("title") != "不导出" for row in bridge.writes)
    bridge.read_only.add("study")
    todos.update_category(study_id, {"name": "学期学习"})
    result = sync.sync(manual=True)
    assert result["status"] != "success"
    assert todos.get_category(study_id)["name"] == "学期学习"
    assert "Reminder list is read only" in next(
        row["name_conflict"] for row in sync.status()["links"] if row["apple_id"] == "study")
    assert todos.get_todo(local["id"])["title"] == "买菜"


@pytest.mark.usefixtures("todos_plugin")
def test_reminder_batch_keeps_undated_children_and_does_not_connect(tmp_path):
    sync, todos, bridge, _clock = reminder_manager(tmp_path, [
        reminder("hw", "study", "作业"),
        reminder("loose", "study", "散任务", due_on=None, due_time=None, planned_on=None),
    ])
    bridge.available = {"study"}
    category = todos.create_category({"name": "学习"})
    preview = sync.preview_batch("import", [{"apple_id": "study", "stella_id": category["id"]}],
                                 "2026-10-01", "2026-10-31")
    assert preview["preview"]["new"] == 1
    with_undated = sync.preview_batch(
        "import", [{"apple_id": "study", "stella_id": category["id"]}],
        "2026-10-01", "2026-10-31", include_undated=True)
    assert with_undated["preview"]["new"] == 2
    parent = todos.set_todo_category(todos.create_todo({
        "title": "父事务", "due_on": "2026-10-12", "timezone": "Asia/Shanghai",
    })["id"], category["id"])
    todos.add_subtask(parent["id"], {"title": "无日期子事务"})
    todos.set_todo_category(todos.create_todo({"title": "单独无日期"})["id"], category["id"])
    exported = sync.preview_batch("export", [{"apple_id": "study", "stella_id": category["id"]}],
                                  "2026-10-01", "2026-10-31")
    assert exported["preview"]["new"] == 2
    result = sync.transfer_batch("export", [{"apple_id": "study", "stella_id": category["id"]}],
                                 "2026-10-01", "2026-10-31", exported["preview_token"], confirm=True)
    assert result["exported"] == 2
    titles = [row["title"] for row in bridge.writes if isinstance(row, dict)]
    assert "父事务" in titles and "无日期子事务" in titles and "单独无日期" not in titles
    assert sync.status()["connected"] is False
    assert sync.status()["links"] == []


def test_link_rows_reject_bad_direction_empty_ids_and_non_bool_enabled():
    with pytest.raises(ValueError, match="direction"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "both", "enabled": True},
        ])
    with pytest.raises(ValueError, match="apple_id"):
        validate_links([
            {"apple_id": "", "stella_id": "study", "direction": "import", "enabled": True},
        ])
    with pytest.raises(ValueError, match="enabled"):
        validate_links([
            {"apple_id": "cal-a", "stella_id": "study", "direction": "import", "enabled": 1},
        ])
