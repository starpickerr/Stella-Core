import json
from datetime import datetime, timezone
import pytest
from tests.elearning_domain import settings, FakeCanvas, config, ElearningSource, DomainServiceCall, SyncError

@pytest.fixture(autouse=True)
def config_path(tmp_path, monkeypatch):
    path = tmp_path / 'elearning/elearning.json'
    monkeypatch.setattr(settings, 'settings_path', lambda: path)
    monkeypatch.setattr('common.state_dir.briefing_db', lambda **_: tmp_path / 'briefing/briefing.db')
    return path

def test_elearning_tool_fetch_uses_shared_crawler_without_briefing_database(config_path, tmp_path, monkeypatch):
    settings.save_settings(config())
    canvas = FakeCanvas()
    db_path = tmp_path / "briefing.db"
    monkeypatch.setattr("common.state_dir.briefing_db", lambda ensure=False: db_path)
    tool = DomainServiceCall(client_factory=lambda cfg: canvas)
    params = {"action": "fetch", "since": "2026-09-08T12:00:00Z", "until": "2026-09-09T00:00:00Z", "limit": 2}
    result = tool.execute(params)
    assert result.status == "success", result.result
    first = json.loads(result.result)
    assert first["total"] == 6 and first["next_offset"] == 2
    assert len(first["source_items"]) == 2
    assert all(item["source"] == "elearning" and item["payload"]["body"] for item in first["source_items"])
    second = json.loads(tool.execute({**params, "offset": 2}).result)
    assert {item["source_id"] for item in first["source_items"]}.isdisjoint(item["source_id"] for item in second["source_items"])
    assert not db_path.exists()
    assert "campus-secret" not in result.result
    calls = list(canvas.calls)
    assert tool.execute({**params, "limit": 0}).status == "error"
    assert tool.execute({**params, "since": "not a date"}).status == "error"
    assert tool.execute({**params, "until": params["since"]}).status == "error"
    assert canvas.calls == calls


def test_elearning_is_discovered_by_mcp_instead_of_builtin_exports():
    import agent.tools as exports
    from agent.tools.tool_manager import ToolManager
    assert 'ElearningTool' not in exports.__all__
    manager=ToolManager()
    manager._load_tools_from_init()
    assert 'elearning' not in manager.tool_classes


def test_elearning_credentials_are_protected_from_file_tools(config_path):
    from agent.permission.gateway import SecurityGateway
    settings.save_settings(config())
    session = settings.session_path(settings.load_settings())
    assert not SecurityGateway.check("full-access", "read", {"path": str(config_path)})
    assert not SecurityGateway.check("full-access", "read", {"path": str(session)})
    assert not SecurityGateway.check("full-access", "bash", {"command": f"cat {session}"})


def test_briefing_keeps_previously_catalogued_course_files(
    config_path, tmp_path, deterministic_briefing_generator
):
    from agent.briefing.pipeline import BriefingPipeline
    from tests.briefing_domain import BriefingService
    from tests.briefing_domain import BriefingStore
    from agent.briefing.sources.base import FetchedItem

    settings.save_settings(config())
    source = settings.elearning_sources()[0]
    source.client_factory = lambda _: FakeCanvas()
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    service.upsert_source_item(FetchedItem(source="elearning", account_id=source.account_id,
        source_id="42:file:4", title="旧课件", occurred_at="2026-09-08T23:00:00Z",
        payload={"resource_type": "file", "body": "旧课件"}).to_catalog_payload())

    detail = BriefingPipeline(service, [source],
        clock=lambda: datetime(2026, 9, 9, tzinfo=timezone.utc)).run()

    assert detail["briefing"].status == "completed"
    assert "42:file:4" in {row["source_id"] for row in detail["mail"]}
    assert "42:assignment:2" in {row["source_id"] for row in detail["mail"]}


def test_quiz_404_does_not_leave_error_on_successful_briefing(
    config_path, tmp_path, deterministic_briefing_generator
):
    from agent.briefing.pipeline import BriefingPipeline
    from tests.briefing_domain import BriefingService
    from tests.briefing_domain import BriefingStore

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
    from tests.briefing_domain import BriefingService
    from tests.briefing_domain import BriefingStore

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
    from tests.briefing_domain import BriefingService
    from tests.briefing_domain import BriefingStore

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
    from tests.briefing_domain import BriefingService
    from tests.briefing_domain import BriefingStore

    settings.save_settings(config(courses=[]))
    source = settings.elearning_sources()[0]
    source.client_factory = lambda cfg: pytest.fail("missing courses must be rejected before login")
    service = BriefingService(BriefingStore(tmp_path / "briefing.db"))
    pipeline = BriefingPipeline(service, [source], clock=lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    detail = pipeline.run()

    assert detail["briefing"].status == "failed"
    assert "尚未选择课程" in detail["briefing"].error_message
