"""Crawler integration tests use fake Canvas responses and private temp files."""
import io
import http.client
import json
from datetime import datetime, timezone
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from agent.briefing import elearning_settings as settings
from agent.briefing.elearning.client import Canvas, SafeRedirect
from agent.briefing.elearning.errors import LoginRequired, SyncError
from agent.briefing.sources.elearning import ElearningSource
from agent.tools.elearning.elearning_tool import ElearningTool

BASE = "https://elearning.fudan.edu.cn"


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "briefing" / "elearning.json"
    monkeypatch.setattr(settings, "settings_path", lambda: path)
    return path


def config(**changes):
    return {**settings.DEFAULTS, "enabled": True, "username": "student", "password": "campus-secret", "courses": ["42"], "request_interval": 0, **changes}


def test_settings_mask_save_replacement_scope_and_deletion(config_path):
    public = settings.save_settings(config())
    assert public["configured"] and public["password_masked"] == "********"
    assert "campus-secret" not in json.dumps(public)
    assert config_path.stat().st_mode & 0o777 == 0o600
    settings.save_settings({"password": "********", "courses": ["43"]})
    assert settings.load_settings()["password"] == "campus-secret"
    settings.save_settings({"password": "replacement"})
    assert settings.load_settings()["password"] == "replacement"
    with pytest.raises(ValueError, match="新账号"):
        settings.save_settings({"username": "other", "password": "********"})
    old_id = public["account_id"]
    other = settings.save_settings({"username": "other", "password": "different"})
    assert other["account_id"] != old_id
    settings.delete_settings()
    assert settings.elearning_sources() == []
    assert settings.public_settings()["username"] == ""


def test_course_names_are_cached_per_account_for_settings(config_path):
    settings.save_settings(config())
    canvas = FakeCanvas()
    with patch("agent.briefing.elearning.client.ensure_login", return_value=canvas):
        assert settings.check_connection({}) == [{"id": "42", "name": "课程"}]
    assert [path for path, _ in canvas.calls] == ["/api/v1/courses"]
    public = settings.public_settings()
    assert public["courses"] == ["42"]
    assert public["course_options"] == [{"id": "42", "name": "课程"}]
    assert "campus-secret" not in json.dumps(public)
    assert settings.course_options_path(settings.load_settings()).stat().st_mode & 0o777 == 0o600
    previous_path = settings.course_options_path(settings.load_settings())
    changed = settings.save_settings({"username": "another", "password": "new-password"})
    assert changed["course_options"] == []
    assert not previous_path.exists()


def test_disabled_source_is_not_available(config_path):
    settings.save_settings(config(enabled=False))
    assert settings.public_settings()["configured"]
    assert settings.elearning_sources() == []


def test_elearning_tool_discovers_courses_before_selection_and_obeys_enabled(config_path):
    settings.save_settings(config(courses=[]))
    canvas = FakeCanvas()
    tool = ElearningTool(client_factory=lambda cfg: canvas)
    result = tool.execute({"action": "courses"})
    assert result.status == "success"
    assert json.loads(result.result) == {"courses": [{"id": "42", "name": "课程"}]}
    assert tool.execute({"action": "fetch"}).status == "error"
    settings.save_settings({"enabled": False})
    canvas.calls.clear()
    assert tool.execute({"action": "courses"}).status == "error"
    assert canvas.calls == []


def test_elearning_tool_fetch_uses_shared_crawler_and_never_commits_cursor(config_path, tmp_path):
    from agent.briefing.store import BriefingStore
    settings.save_settings(config())
    canvas = FakeCanvas()
    store = BriefingStore(tmp_path / "briefing.db")
    tool = ElearningTool(client_factory=lambda cfg: canvas, store=store)
    params = {"action": "fetch", "since": "2026-09-08T12:00:00Z", "until": "2026-09-09T00:00:00Z", "limit": 2}
    result = tool.execute(params)
    assert result.status == "success", result.result
    first = json.loads(result.result)
    assert first["total"] == 6 and first["next_offset"] == 2
    assert len(first["source_items"]) == 2
    assert all(item["source"] == "elearning" and item["payload"]["body"] for item in first["source_items"])
    second = json.loads(tool.execute({**params, "offset": 2}).result)
    assert {item["source_id"] for item in first["source_items"]}.isdisjoint(item["source_id"] for item in second["source_items"])
    assert store.get_cursor("elearning", settings.account_id(settings.load_settings()), "elearning_state") is None
    assert store.list_briefings() == []
    assert "campus-secret" not in result.result
    calls = list(canvas.calls)
    assert tool.execute({**params, "limit": 0}).status == "error"
    assert tool.execute({**params, "since": "not a date"}).status == "error"
    assert tool.execute({**params, "until": params["since"]}).status == "error"
    assert canvas.calls == calls


def test_elearning_tool_is_registered_and_read_only():
    import agent.tools as exports
    from agent.permission.gateway import SecurityGateway
    check_tool_call = SecurityGateway.check
    from agent.tools.tool_manager import ToolManager
    assert "ElearningTool" in exports.__all__
    assert exports.ElearningTool is ElearningTool
    manager = ToolManager()
    manager._load_tools_from_init()
    assert manager.tool_classes["elearning"] is ElearningTool
    for action in ("courses", "fetch"):
        assert check_tool_call("read-only", "elearning", {"action": action})
    assert not check_tool_call("read-only", "elearning", {"action": "sync_files"})
    assert check_tool_call("workspace-write", "elearning", {"action": "sync_files"})


def test_elearning_credentials_are_protected_from_file_tools(config_path):
    from agent.permission.gateway import SecurityGateway
    settings.save_settings(config())
    session = settings.session_path(settings.load_settings())
    assert not SecurityGateway.check("full-access", "read", {"path": str(config_path)})
    assert not SecurityGateway.check("full-access", "read", {"path": str(session)})
    assert not SecurityGateway.check("full-access", "bash", {"command": f"cat {session}"})


def test_elearning_tool_syncs_selected_files_only_to_granted_folder(config_path, tmp_path, security_audit_path):
    root = tmp_path / "selected"
    root.mkdir()
    settings.save_settings(config(file_sync_enabled=True, file_sync_root=str(root)))
    canvas = FakeCanvas()
    canvas.rows["files"] = [
        {"id": 4, "filename": "讲义.pdf", "url": BASE + "/files/4/download"},
        {"id": 5, "filename": "作业.pdf", "url": BASE + "/files/5/download"},
    ]
    canvas.open = Mock(return_value=io.BytesIO(b"pdf"))
    tool = ElearningTool(client_factory=lambda _: canvas)
    result = tool.execute({"action": "sync_files", "file_ids": ["5"]})
    assert result.status == "success", result.result
    assert json.loads(result.result) == {"status": "completed", "total": 1, "processed": 1,
                                        "next_offset": None, "save_root": str(root), "errors": []}
    assert (root / "课程--42" / "作业--5.pdf").read_bytes() == b"pdf"
    assert not (root / "课程--42" / "讲义--4.pdf").exists()
    assert tool.execute({"action": "sync_files", "course_ids": ["unselected"]}).status == "error"
    assert tool.execute({"action": "sync_files", "limit": 0}).status == "error"
    missing = json.loads(tool.execute({"action": "sync_files", "file_ids": ["missing"]}).result)
    assert missing["status"] == "partial" and "missing" in missing["errors"][0]
    page = json.loads(tool.execute({"action": "sync_files", "limit": 1}).result)
    assert page["total"] == 2 and page["next_offset"] == 1
    settings.save_settings({"file_sync_enabled": False})
    assert "开启课程文件同步" in tool.execute({"action": "sync_files"}).result


class FakeCanvas:
    base = BASE

    def __init__(self):
        self.calls = []
        self.rows = {
            "courses": [{"id": 42, "name": "课程"}],
            "discussion_topics": [{"id": 1, "title": "公告", "message": "<p>上课通知</p><script>ignore</script>", "posted_at": "2026-09-08T23:00:00Z"}],
            "assignments": [{"id": 2, "name": "作业", "description": "<p>完整作业说明</p>", "updated_at": "2026-09-08T23:00:00Z",
                             "due_at": "2026-09-10T12:00:00Z", "points_possible": 100,
                             "submission": {"workflow_state": "graded", "graded_at": "2026-09-08T23:00:00Z", "score": 0}}],
            "quizzes": [{"id": 3, "title": "测试", "description": "测试要求", "updated_at": "2026-09-08T23:00:00Z"}],
            "files": [{"id": 4, "display_name": "讲义.pdf", "size": 123, "updated_at": "2026-09-08T23:00:00Z"}],
            "enrollments": [{"id": 5, "grades": {"current_score": 0}}],
        }

    def get(self, path, params=None):
        return {"id": 99}, None

    def list(self, path, params=None):
        self.calls.append((path, params))
        rows = self.rows[path.rsplit("/", 1)[-1]]
        if isinstance(rows, Exception):
            raise rows
        return rows


def test_canvas_resources_use_source_items_full_body_and_event_time(config_path):
    canvas = FakeCanvas()
    canvas.rows["discussion_topics"].append({"id": 9, "title": "未发布", "published": False})
    source = ElearningSource(config(), client_factory=lambda cfg: canvas)
    result = source.fetch({"since": "2026-09-08T12:00:00Z", "until": "2026-09-09T00:00:00Z"})
    assert result.errors == []
    assert {item.payload["resource_type"] for item in result.items} == {"announcement", "assignment", "quiz", "grade", "course_grade", "file"}
    assert all(item.source == "elearning" and item.account_id == source.account_id for item in result.items)
    assignment = next(item for item in result.items if item.payload["resource_type"] == "assignment")
    assert "完整作业说明" in assignment.payload["body"]
    assert assignment.occurred_at == "2026-09-08T23:00:00Z" and assignment.payload["due_at"] == "2026-09-10T12:00:00Z"
    assert "ignore" not in next(item for item in result.items if item.payload["resource_type"] == "announcement").payload["body"]
    assert "0 / 100" in next(item for item in result.items if item.payload["resource_type"] == "grade").payload["body"]
    assert not any("未发布" in item.title for item in result.items)
    again = source.fetch({**result.cursors, "since": "2026-09-09T00:00:00Z", "until": "2026-09-10T00:00:00Z"})
    assert again.items == []


def test_new_pending_task_and_changes_without_server_dates_are_observed_once(config_path):
    canvas = FakeCanvas()
    canvas.rows["assignments"] = [{"id": 2, "name": "旧发布待完成作业", "created_at": "2026-01-01T00:00:00Z", "description": "要求",
                                   "submission": {"workflow_state": "unsubmitted"}}]
    source = ElearningSource(config(), client_factory=lambda cfg: canvas)
    first = source.fetch({"since": "2026-09-08T12:00:00Z", "until": "2026-09-09T00:00:00Z"})
    assert next(item for item in first.items if item.payload["resource_type"] == "assignment").occurred_at == "2026-09-09T00:00:00Z"
    canvas.rows["assignments"][0]["description"] = "要求有修改"
    changed = source.fetch({**first.cursors, "since": "2026-09-09T00:00:00Z", "until": "2026-09-10T00:00:00Z"})
    assignment = next(item for item in changed.items if item.payload["resource_type"] == "assignment")
    assert assignment.occurred_at == "2026-09-10T00:00:00Z" and "要求有修改" in assignment.payload["body"]


def test_partial_canvas_read_reports_failure_without_advancing_state(config_path):
    canvas = FakeCanvas()
    canvas.rows["quizzes"] = SyncError("网站返回 HTTP 403")
    result = ElearningSource(config(), client_factory=lambda cfg: canvas).fetch({})
    assert result.items and result.errors and result.cursors == {}
    canvas.rows["quizzes"] = LoginRequired("expired")
    with pytest.raises(LoginRequired):
        ElearningSource(config(), client_factory=lambda cfg: canvas).fetch({})


def test_quiz_404_keeps_other_candidates_without_marking_source_partial(config_path):
    canvas = FakeCanvas()
    canvas.rows["courses"] = [{"id": i, "name": "课程" + str(i)} for i in range(1, 10)]
    canvas.rows["quizzes"] = SyncError("网站返回 HTTP 404。")
    source = ElearningSource(config(courses=[str(i) for i in range(1, 10)]), client_factory=lambda cfg: canvas)
    result = source.fetch({"since": "2026-09-08T12:00:00Z", "until": "2026-09-09T00:00:00Z"})
    assert result.errors == []
    assert "elearning_state" in result.cursors
    assert result.items and all(item.payload["resource_type"] != "quiz" for item in result.items)
    assert {item.payload["resource_type"] for item in result.items} >= {"announcement", "assignment", "file"}


def test_quiz_404_does_not_leave_error_on_successful_briefing(
    config_path, tmp_path, deterministic_briefing_generator
):
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.service import BriefingService
    from agent.briefing.store import BriefingStore

    canvas = FakeCanvas()
    canvas.rows["quizzes"] = SyncError("网站返回 HTTP 404。")
    source = ElearningSource(config(), client_factory=lambda cfg: canvas)
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    pipeline = BriefingPipeline(service, [source], clock=lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    detail = pipeline.run()

    assert detail["briefing"].status == "completed"
    assert detail["briefing"].error_message == ""
    assert detail["mail"]


def test_successful_update_clears_previous_fetch_error(
    config_path, tmp_path, deterministic_briefing_generator
):
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.service import BriefingService
    from agent.briefing.store import BriefingStore

    canvas = FakeCanvas()
    canvas.rows["quizzes"] = SyncError("网站返回 HTTP 403。")
    source = ElearningSource(config(), client_factory=lambda cfg: canvas)
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    pipeline = BriefingPipeline(service, [source], clock=lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    first = pipeline.run()
    assert first["briefing"].status == "partial"
    assert "HTTP 403" in first["briefing"].error_message

    canvas.rows["quizzes"] = SyncError("网站返回 HTTP 404。")
    updated = pipeline.run(operation="update")
    assert updated["briefing"].status == "completed"
    assert updated["briefing"].error_message == ""


def test_invalid_saved_course_is_reported_by_actual_generation(
    config_path, tmp_path, deterministic_briefing_generator
):
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.service import BriefingService
    from agent.briefing.store import BriefingStore

    source = ElearningSource(config(courses=["missing-course"]), client_factory=lambda cfg: FakeCanvas())
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    pipeline = BriefingPipeline(service, [source], clock=lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    detail = pipeline.run()

    assert detail["briefing"].status == "failed"
    assert "missing-course" in detail["briefing"].error_message
    assert "重新选择课程" in detail["briefing"].error_message


def test_enabled_source_without_tested_course_is_not_silently_skipped(
    config_path, tmp_path, deterministic_briefing_generator
):
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.service import BriefingService
    from agent.briefing.store import BriefingStore

    settings.save_settings(config(courses=[]))
    source = settings.elearning_sources()[0]
    source.client_factory = lambda cfg: pytest.fail("missing courses must be rejected before login")
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    pipeline = BriefingPipeline(service, [source], clock=lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    detail = pipeline.run()

    assert detail["briefing"].status == "failed"
    assert "尚未选择课程" in detail["briefing"].error_message


def test_canvas_token_pagination_is_scoped_to_config_and_origin(config_path, monkeypatch):
    # The shared process's CANVAS_TOKEN must never override this source's login.
    monkeypatch.setenv("CANVAS_TOKEN", "other-account-token")
    client = Canvas(config(token="own-token"), auto_login=False)
    assert client.token == "own-token"
    response = io.BytesIO(b'[{"id": 1}]')
    response.headers = {"Content-Type": "application/json"}
    response.geturl = lambda: BASE + "/api/v1/courses"
    client.opener.open = Mock(return_value=response)
    assert client.list("/api/v1/courses") == [{"id": 1}]
    request = client.opener.open.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer own-token"
    with pytest.raises(SyncError, match="不属于"):
        client.get("https://outside.example/api/v1/courses")


def test_cookie_login_is_scoped_and_renewed_once_without_exposing_secrets(config_path, monkeypatch):
    cfg = config()
    settings.save_session(cfg, {"cookies": [{"domain": "elearning.fudan.edu.cn", "name": "session", "value": "private-cookie", "expires": -1}]})
    client = Canvas(cfg)
    assert client.token == "" and len(list(client.cookie_jar)) == 1
    opens = []

    def open_once(url, api=True):
        opens.append(url)
        if len(opens) == 1:
            raise LoginRequired("expired")
        return "response"

    monkeypatch.setattr(client, "_open", open_once)
    renewed = Mock()
    monkeypatch.setattr(client, "_renew_login", renewed)
    assert client.open("/api/v1/courses") == "response"
    renewed.assert_called_once_with()
    assert len(opens) == 2


def test_crawler_file_fallback_reads_modules_without_downloading(config_path):
    canvas = FakeCanvas()
    canvas.rows["files"] = SyncError("网站返回 HTTP 403")
    canvas.rows["modules"] = [{"id": 6}]
    canvas.rows["items"] = [{"type": "File", "content_id": 7}]
    canvas.get = lambda path, params=None: ({"id": 99}, None) if path.endswith("profile") else (
        {"id": 7, "display_name": "单元文件.pdf", "updated_at": "2026-09-08T23:00:00Z"}, None)
    result = ElearningSource(config(), client_factory=lambda cfg: canvas).fetch({})
    assert any(item.payload["resource_type"] == "file" and "单元文件" in item.title for item in result.items)
    assert result.errors and result.cursors == {}


def test_file_sync_creates_course_folder_and_preserves_local_edits(config_path, tmp_path, security_audit_path):
    from agent.briefing.elearning.file_sync import sync_files

    root = tmp_path / "project"
    root.mkdir()
    settings.save_settings(config(file_sync_enabled=True, file_sync_root=str(root)))
    cfg = settings.load_settings()
    course = {"id": 42, "name": "课程"}
    raw = {"id": 4, "filename": "讲义.pdf", "size": 5, "updated_at": "v1", "url": BASE + "/files/4/download"}
    client = Mock()
    client.open.side_effect = lambda *args, **kwargs: io.BytesIO(client.content)
    client.content = b"first"

    assert sync_files(client, cfg, [(course, raw)]) == []
    saved = root / "课程--42" / "讲义--4.pdf"
    assert saved.read_bytes() == b"first"
    assert sync_files(client, cfg, [(course, raw)]) == []
    assert client.open.call_count == 1

    raw["updated_at"] = "v2"
    client.content = b"newer"
    assert sync_files(client, cfg, [(course, raw)]) == []
    assert saved.read_bytes() == b"newer"

    saved.write_bytes(b"my notes")
    raw["updated_at"] = "v3"
    client.content = b"third"
    assert sync_files(client, cfg, [(course, raw)]) == []
    assert saved.read_bytes() == b"my notes"
    assert any(path.read_bytes() == b"third" for path in saved.parent.iterdir() if path != saved)
    assert len(security_audit_path.read_text().splitlines()) >= 4


def test_file_sync_rejects_symlink_escape_and_revoked_grant(config_path, tmp_path, monkeypatch):
    from agent.briefing.elearning.file_sync import sync_files

    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    settings.save_settings(config(file_sync_enabled=True, file_sync_root=str(root)))
    cfg = settings.load_settings()
    course = {"id": 42, "name": "课程"}
    raw = {"id": 4, "filename": "讲义.pdf", "url": BASE + "/files/4/download"}
    (root / "课程--42").symlink_to(outside, target_is_directory=True)
    client = Mock()
    assert "安全目录" in sync_files(client, cfg, [(course, raw)])[0]
    assert list(outside.iterdir()) == []
    client.open.assert_not_called()

    settings.save_settings({"file_sync_enabled": False})
    assert "授权已变更" in sync_files(client, cfg, [(course, raw)])[0]
    client.open.assert_not_called()


def test_file_sync_retries_incomplete_response_without_leaving_partial_file(config_path, tmp_path, monkeypatch):
    from agent.briefing.elearning.file_sync import sync_files

    root = tmp_path / "selected"
    root.mkdir()
    settings.save_settings(config(file_sync_enabled=True, file_sync_root=str(root)))
    monkeypatch.setattr("agent.briefing.elearning.file_sync.time.sleep", lambda _: None)
    course = {"id": 42, "name": "课程"}
    raw = {"id": 4, "filename": "讲义.pdf", "url": BASE + "/files/4/download"}

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            raise http.client.IncompleteRead(b"partial", 10)

    client = Mock()
    client.open.side_effect = [Interrupted(), io.BytesIO(b"complete")]
    assert sync_files(client, settings.load_settings(), [(course, raw)]) == []
    folder = root / "课程--42"
    assert (folder / "讲义--4.pdf").read_bytes() == b"complete"
    assert not any(path.name.startswith(".elearning-") for path in folder.iterdir())
    assert client.open.call_count == 2


def test_briefing_source_only_downloads_with_explicit_sync_setting(config_path, tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    settings.save_settings(config(file_sync_enabled=True, file_sync_root=str(root)))
    canvas = FakeCanvas()
    canvas.rows["files"][0]["filename"] = "讲义.pdf"
    canvas.rows["files"][0]["url"] = BASE + "/files/4/download"
    canvas.open = Mock(return_value=io.BytesIO(b"pdf"))
    cfg = settings.load_settings()

    assert ElearningSource(cfg, client_factory=lambda _: canvas).fetch({}).errors == []
    canvas.open.assert_not_called()
    result = ElearningSource(cfg, client_factory=lambda _: canvas, auto_sync_files=True).fetch({})
    assert result.errors == []
    assert (root / "课程--42" / "讲义--4.pdf").read_bytes() == b"pdf"
