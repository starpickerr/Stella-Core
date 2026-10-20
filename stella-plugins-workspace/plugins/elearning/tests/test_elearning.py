import io
import http.client
import json
import threading
import time
import urllib.error
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch
import pytest
from stella_elearning_test_support import settings, Canvas, ElearningSource, ServiceCall as ElearningTool
from stella_elearning_test_support import LoginRequired, SyncCancelled, SyncError, client, ElearningStore
from stella_elearning_test_support.fakes import config, FakeCanvas, BASE, _capture_cancel
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
    with patch("stella_elearning_domain_tests.service.ensure_login", return_value=canvas):
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


def test_connection_test_discovers_courses_without_changing_directory(config_path, tmp_path):
    settings.save_settings(config(enabled=False, courses=[]))
    canvas = FakeCanvas()
    with patch("stella_elearning_domain_tests.service.ensure_login", return_value=canvas):
        rows = settings.check_connection({"file_sync_enabled": True,
                                          "file_sync_root": str(tmp_path)})
    assert rows == [{"id": "42", "name": "课程"}]
    assert settings.load_settings()["file_sync_root"] == ""


def test_disabled_source_is_not_available(config_path):
    settings.save_settings(config(enabled=False))
    assert settings.public_settings()["configured"]
    assert settings.elearning_sources() == []


def test_elearning_tool_discovers_and_fetches_without_briefing_selection(config_path):
    settings.save_settings(config(courses=[], enabled=False))
    canvas = FakeCanvas()
    tool = ElearningTool(client_factory=lambda cfg: canvas)
    result = tool.execute({"action": "courses"})
    assert result.status == "success"
    assert json.loads(result.result) == {"courses": [{"id": "42", "name": "课程"}]}
    fetched = tool.execute({"action": "fetch", "since": "2026-09-08T12:00:00Z",
                            "until": "2026-09-09T00:00:00Z"})
    assert fetched.status == "success", fetched.result
    assert json.loads(fetched.result)["total"] == 6
    assert tool.execute({"action": "fetch", "course_ids": ["99"]}).status == "error"


def test_canvas_cancel_interrupts_request_spacing_without_waiting_for_network(config_path):
    event = threading.Event()
    client = Canvas(config(token="token", request_interval=30), auto_login=False, cancel_event=event)
    entered = threading.Event()
    result = []
    original_wait = client.wait

    def waiting(seconds):
        entered.set()
        return original_wait(seconds)

    client.wait = waiting
    client.opener.open = Mock(side_effect=AssertionError("request should never start"))
    worker = threading.Thread(target=lambda: result.append(_capture_cancel(client)), daemon=True)
    worker.start()
    assert entered.wait(1)
    started = time.monotonic()
    event.set()
    worker.join(1)
    assert not worker.is_alive()
    assert time.monotonic() - started < 1
    assert result == ["cancelled"]
    client.opener.open.assert_not_called()


def test_canvas_cancel_stops_retry_and_uses_bounded_socket_timeout(config_path):
    event = threading.Event()
    client = Canvas(config(token="token"), auto_login=False, cancel_event=event)

    def fail_first(_request, timeout):
        assert timeout == 5
        event.set()
        raise urllib.error.URLError("temporary outage")

    client.opener.open = Mock(side_effect=fail_first)
    with pytest.raises(SyncCancelled):
        client.get("/api/v1/courses")
    client.opener.open.assert_called_once()


def test_elearning_fetch_stops_after_current_resource_when_cancelled(config_path):
    settings.save_settings(config())
    event = threading.Event()
    canvas = FakeCanvas()
    original_list = canvas.list

    def cancel_during_first_resource(path, params=None):
        rows = original_list(path, params)
        if path.endswith("discussion_topics"):
            event.set()
        return rows

    canvas.list = cancel_during_first_resource
    tool = ElearningTool(client_factory=lambda _: canvas)
    tool.cancel_event = event
    result = tool.execute({"action": "fetch"})
    assert result.status == "error" and "已取消" in result.result
    assert [path.rsplit("/", 1)[-1] for path, _ in canvas.calls] == ["courses", "assignments", "discussion_topics"]


def test_cancelled_elearning_tool_returns_so_next_session_work_can_run(config_path):
    settings.save_settings(config(token="token", request_interval=30))
    entered = threading.Event()
    event = threading.Event()
    canvas = Canvas(config(token="token", request_interval=30), auto_login=False)
    original_wait = canvas.wait

    def waiting(seconds):
        entered.set()
        return original_wait(seconds)

    canvas.wait = waiting
    canvas.opener.open = Mock(side_effect=AssertionError("request should not start"))
    tool = ElearningTool(client_factory=lambda _: canvas)
    tool.cancel_event = event
    results = []
    worker = threading.Thread(target=lambda: results.append(tool.execute({"action": "courses"})), daemon=True)
    worker.start()
    assert entered.wait(1)
    event.set()
    worker.join(1)
    assert not worker.is_alive()
    assert results[0].status == "error" and "已取消" in results[0].result
    next_tool = ElearningTool(client_factory=lambda _: FakeCanvas())
    assert next_tool.execute({"action": "courses"}).status == "success"


def test_elearning_tool_syncs_selected_files_only_to_configured_folder(config_path, tmp_path, security_audit_path):
    root = tmp_path / "selected"
    root.mkdir()
    settings.save_settings(config(enabled=False, file_sync_root=str(root)))
    canvas = FakeCanvas()
    canvas.rows["files"] = [
        {"id": 4, "filename": "讲义.pdf", "url": BASE + "/files/4/download"},
        {"id": 5, "filename": "作业.pdf", "url": BASE + "/files/5/download"},
    ]
    canvas.open = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(b"pdf"))
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
    settings.save_file_sync_settings("")
    assert "eLearning 设置中选择课件保存目录" in tool.execute({"action": "sync_files"}).result


def test_elearning_lists_live_files_and_filters_downloads_without_scripts(config_path, tmp_path, security_audit_path):
    root = tmp_path / "selected"
    root.mkdir()
    settings.save_settings(config(enabled=False, file_sync_root=str(root)))
    canvas = FakeCanvas()
    canvas.rows["files"] = [
        {"id": 4, "filename": "第一讲.PDF", "size": 3, "url": BASE + "/files/4/download"},
        {"id": 5, "filename": "第二讲.pptx", "size": 3, "url": BASE + "/files/5/download"},
        {"id": 6, "filename": "成绩.csv", "size": 3, "url": BASE + "/files/6/download"},
    ]
    canvas.open = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(b"pdf"))
    tool = ElearningTool(client_factory=lambda _: canvas)

    first = json.loads(tool.execute({"action": "list_files", "file_extensions": [".PDF", "pptx"], "limit": 1}).result)
    second = json.loads(tool.execute({"action": "list_files", "file_extensions": ["pdf", "pptx"], "offset": 1}).result)
    assert first["total"] == 2 and first["next_offset"] == 1
    assert [first["files"][0]["file_id"], second["files"][0]["file_id"]] == ["4", "5"]
    assert second["next_offset"] is None
    assert "url" not in first["files"][0]  # signed download links remain inside the connector
    assert tool.execute({"action": "list_files", "file_extensions": ["../secret"]}).status == "error"
    canvas.open.assert_not_called()

    result = json.loads(tool.execute({"action": "sync_files", "file_extensions": ["pdf", "pptx"]}).result)
    assert result["status"] == "completed" and result["total"] == 2
    assert len(list((root / "课程--42").iterdir())) == 2
    assert not (root / "课程--42" / "成绩--6.csv").exists()


def test_headless_auto_login_retries_transient_verification_without_connection_test(config_path):
    canvas_module = client

    browser = Mock()
    context = browser.new_context.return_value
    page = context.new_page.return_value
    page.url = "https://id.fudan.edu.cn/login"
    page.is_closed.return_value = False
    # Playwright only delivers the SSO redirect while its sync API is pumping events.
    page.wait_for_timeout.side_effect = lambda _: setattr(page, "url", BASE)
    context.cookies.return_value = []
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value = browser
    verified = Mock()
    verified.get.side_effect = [SyncError("临时网络超时"), ({"id": 7}, None)]
    verified.session_data.return_value = {"cookies": []}
    event = Mock()
    event.is_set.return_value = False
    event.wait.return_value = False

    with patch("playwright.sync_api.sync_playwright", return_value=playwright), \
         patch.object(canvas_module, "Canvas", return_value=verified), \
         patch.object(ElearningStore, "save_session") as save:
        canvas_module.login(config(), settings.store(), cancel_event=event)

    assert verified.get.call_count == 2
    save.assert_called_once()
    page.wait_for_timeout.assert_called()
    event.wait.assert_not_called()
    assert playwright.__enter__.return_value.chromium.launch.call_args.kwargs["headless"] is True
    browser.close.assert_called_once()


def test_headless_auto_login_can_cancel_during_browser_wait(config_path):
    canvas_module = client

    browser = Mock()
    page = browser.new_context.return_value.new_page.return_value
    page.url = "https://id.fudan.edu.cn/login"
    page.is_closed.return_value = False
    event = threading.Event()
    page.wait_for_timeout.side_effect = lambda _: event.set()
    playwright = MagicMock()
    playwright.__enter__.return_value.chromium.launch.return_value = browser

    with patch("playwright.sync_api.sync_playwright", return_value=playwright):
        with pytest.raises(SyncCancelled):
            canvas_module.login(config(), settings.store(), cancel_event=event)

    page.wait_for_timeout.assert_called_once_with(250)
    browser.close.assert_called_once()


def test_live_file_inventory_reports_expired_login_as_failure(config_path):
    settings.save_settings(config())
    canvas = FakeCanvas()
    canvas.rows["files"] = LoginRequired("登录已失效")
    result = ElearningTool(client_factory=lambda _: canvas).execute({"action": "list_files"})
    assert result.status == "error"
    assert "登录已失效" in result.result


def test_courseware_layout_adopts_existing_original_name_and_blocks_symlink(config_path, tmp_path, security_audit_path):
    root = tmp_path / "selected"
    materials = root / "计算机网络" / "课件"
    materials.mkdir(parents=True)
    (materials / "讲义.pdf").write_bytes(b"pdf")
    settings.save_settings(config(file_sync_root=str(root)))
    canvas = FakeCanvas()
    canvas.rows["courses"] = [{"id": 42, "name": "CS30066.01 计算机网络"}]
    canvas.rows["files"] = [
        {"id": 4, "filename": "讲义.pdf", "url": BASE + "/files/4/download"},
        {"id": 5, "filename": "脚本.py", "url": BASE + "/files/5/download"},
    ]
    canvas.open = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(b"pdf"))
    tool = ElearningTool(client_factory=lambda _: canvas)
    args = {"action": "sync_files", "layout": "courseware", "file_extensions": ["pdf", "ppt", "pptx"]}

    first = json.loads(tool.execute(args).result)
    assert first["status"] == "completed" and first["total"] == 1
    assert [p.name for p in materials.iterdir()] == ["讲义.pdf"]
    assert (materials / "讲义.pdf").read_bytes() == b"pdf"
    assert canvas.open.call_count == 1
    assert json.loads(tool.execute(args).result)["status"] == "completed"
    assert canvas.open.call_count == 1  # manifest now owns the existing matching file

    outside = tmp_path / "outside"
    outside.mkdir()
    unsafe = root / "其他课程"
    unsafe.symlink_to(outside, target_is_directory=True)
    canvas.rows["courses"] = [{"id": 42, "name": "其他课程"}]
    # A new layout manifest maps this course to its original safe directory;
    # exercise a fresh account so the symlink is the first candidate.
    settings.save_settings({"username": "another", "password": "replacement", "courses": ["42"],
                            "file_sync_root": str(root)})
    result = json.loads(tool.execute(args).result)
    assert result["status"] == "partial"
    assert "安全目录" in result["errors"][0]
    assert list(outside.iterdir()) == []


def test_cancel_during_file_download_removes_partial_file(config_path, tmp_path, security_audit_path):
    root = tmp_path / "selected"
    root.mkdir()
    settings.save_settings(config(file_sync_root=str(root)))
    canvas = FakeCanvas()
    canvas.rows["files"] = [{"id": 4, "filename": "讲义.pdf", "url": BASE + "/files/4/download"}]
    event = threading.Event()

    class CancelAfterFirstBlock(io.BytesIO):
        def read(self, size=-1):
            block = super().read(size)
            event.set()
            return block

    canvas.open = Mock(return_value=CancelAfterFirstBlock(b"pdf"))
    tool = ElearningTool(client_factory=lambda _: canvas)
    tool.cancel_event = event
    result = tool.execute({"action": "sync_files"})
    assert result.status == "error" and "已取消" in result.result
    folder = root / "课程--42"
    assert folder.is_dir() and list(folder.iterdir()) == []


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


def test_briefing_reads_broad_metadata_progressively_without_downloading(config_path):
    settings.save_settings(config())
    canvas = FakeCanvas()
    canvas.open = Mock(side_effect=AssertionError("briefing must not download files"))
    source = settings.elearning_sources()[0]
    source.client_factory = lambda _: canvas
    source.auto_sync_files = True
    source.config["file_sync_enabled"] = True
    previews = []
    source.on_items_ready = lambda items: previews.append({item.payload["resource_type"] for item in items})

    result = source.fetch({"since": "2026-09-08T12:00:00Z", "until": "2026-09-09T00:00:00Z"})

    assert result.errors == []
    assert {item.payload["resource_type"] for item in result.items} == {
        "announcement", "assignment", "quiz", "grade", "course_grade", "file"}
    assert previews[0] == {"assignment", "grade"}
    assert previews[-1] == {item.payload["resource_type"] for item in result.items}
    assert {path.rsplit("/", 1)[-1] for path, _ in canvas.calls} >= {
        "courses", "assignments", "discussion_topics", "quizzes", "files", "enrollments"}
    canvas.open.assert_not_called()


def test_briefing_file_metadata_stops_at_previous_window(config_path):
    from stella_elearning_domain_tests.courses import list_recent_files

    canvas = FakeCanvas()
    canvas.get = Mock(side_effect=[
        ([{"id": 11, "updated_at": "2026-09-08T23:00:00Z"}], "page-2"),
        ([{"id": 12, "updated_at": "2026-09-08T20:00:00Z"},
          {"id": 13, "updated_at": "2026-09-01T00:00:00Z"}], "page-3"),
    ])
    rows, warnings = list_recent_files(canvas, 42, datetime(2026, 9, 8, 12, tzinfo=timezone.utc))

    assert [row["id"] for row in rows] == [11, 12]
    assert warnings == []
    assert canvas.get.call_count == 2
    assert canvas.get.call_args_list[0].args[0] == "/api/v1/courses/42/files"
    assert canvas.get.call_args_list[0].args[1]["sort"] == "updated_at"


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
    from stella_elearning_test_support import sync_files

    root = tmp_path / "project"
    root.mkdir()
    settings.save_settings(config(file_sync_root=str(root)))
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
    assert saved.read_bytes() == b"first"
    current = next(path for path in saved.parent.iterdir() if path.read_bytes() == b"newer")
    current.write_bytes(b"my notes")
    raw["updated_at"] = "v3"
    client.content = b"third"
    assert sync_files(client, cfg, [(course, raw)]) == []
    assert saved.read_bytes() == b"first"
    assert current.read_bytes() == b"my notes"
    assert any(path.read_bytes() == b"third" for path in saved.parent.iterdir() if path not in (saved, current))
    assert len(security_audit_path.read_text().splitlines()) >= 4


def test_file_sync_rejects_symlink_escape_and_changed_configuration(config_path, tmp_path, monkeypatch):
    from stella_elearning_test_support import sync_files

    root, outside = tmp_path / "project", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    settings.save_settings(config(file_sync_root=str(root)))
    cfg = settings.load_settings()
    course = {"id": 42, "name": "课程"}
    raw = {"id": 4, "filename": "讲义.pdf", "url": BASE + "/files/4/download"}
    (root / "课程--42").symlink_to(outside, target_is_directory=True)
    client = Mock()
    assert "安全目录" in sync_files(client, cfg, [(course, raw)])[0]
    assert list(outside.iterdir()) == []
    client.open.assert_not_called()

    settings.save_file_sync_settings("")
    assert "设置已变更" in sync_files(client, cfg, [(course, raw)])[0]
    client.open.assert_not_called()


def test_file_sync_retries_incomplete_response_without_leaving_partial_file(config_path, tmp_path, monkeypatch):
    from stella_elearning_test_support import sync_files

    root = tmp_path / "selected"
    root.mkdir()
    settings.save_settings(config(file_sync_root=str(root)))
    monkeypatch.setattr("stella_elearning_domain_tests.file_sync.time.sleep", lambda _: None)
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


def test_briefing_source_never_downloads_with_legacy_auto_sync_setting(config_path, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    settings.save_settings(config(file_sync_root=str(root)))
    canvas = FakeCanvas()
    canvas.rows["files"][0]["filename"] = "讲义.pdf"
    canvas.rows["files"][0]["url"] = BASE + "/files/4/download"
    canvas.open = Mock(side_effect=AssertionError("briefing must not download files"))
    cfg = settings.load_settings()

    assert ElearningSource(cfg, client_factory=lambda _: canvas).fetch({}).errors == []
    canvas.open.assert_not_called()
    result = ElearningSource({**cfg, 'auto_sync_files': True}, client_factory=lambda _: canvas).fetch({})
    assert result.errors == []
    assert not list(root.iterdir())
    canvas.open.assert_not_called()
