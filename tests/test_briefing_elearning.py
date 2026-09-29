"""Crawler integration tests use fake Canvas responses and private temp files."""
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent.briefing import elearning_settings as settings
from agent.briefing.elearning.client import Canvas, SafeRedirect
from agent.briefing.elearning.errors import LoginRequired, SyncError
from agent.briefing.sources.elearning import ElearningSource

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


def test_disabled_source_is_not_available(config_path):
    settings.save_settings(config(enabled=False))
    assert settings.public_settings()["configured"]
    assert settings.elearning_sources() == []


def test_import_crawler_copies_only_configuration_and_session_to_private_state(config_path, tmp_path):
    root = tmp_path / "crawler"
    (root / "config").mkdir(parents=True)
    (root / ".private").mkdir()
    (root / "config/config.yaml").write_text("base_url: https://elearning.fudan.edu.cn\ncourses: [42]\noutput_dir: data/output\n")
    (root / ".env").write_text("ELEARNING_USERNAME='student'\nELEARNING_PASSWORD='p$${literal}#ass'\nCANVAS_TOKEN='token-secret'\n")
    cookie = {"cookies": [{"domain": "elearning.fudan.edu.cn", "name": "session", "value": "cookie-secret"}]}
    (root / ".private/session.json").write_text(json.dumps(cookie))
    before = (root / ".env").read_bytes()
    public = settings.import_crawler(str(root))
    assert public["courses"] == ["42"] and public["enabled"]
    assert "secret" not in json.dumps(public) and "${literal}" not in json.dumps(public)
    saved = settings.load_settings()
    assert saved["password"] == "p$${literal}#ass"
    assert json.loads(settings.session_path(saved).read_text()) == cookie
    assert settings.session_path(saved).stat().st_mode & 0o777 == 0o600
    assert (root / ".env").read_bytes() == before
    assert not (config_path.parent / "output_dir").exists()


def test_invalid_import_leaves_existing_settings(config_path, tmp_path):
    settings.save_settings(config())
    before = config_path.read_bytes()
    with pytest.raises(ValueError, match="无法导入"):
        settings.import_crawler(str(tmp_path / "missing"))
    assert config_path.read_bytes() == before


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
