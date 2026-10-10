"""Exercise the real Agent tool loop using a scripted model, never a provider."""
import json
import sqlite3
import threading
from datetime import datetime

import pytest

from agent.briefing.generator import (AgentBriefingGenerator, BriefingAgent, ReadSourceTool,
                                      ResultTool, decision_schema, validate_body, validate_decisions)
from agent.briefing.instructions import DEFAULT_RULE_TEXT
from agent.briefing.pipeline import BriefingPipeline
from agent.briefing.service import BriefingService
from agent.briefing.sources.base import FetchedItem
from briefing_fakes import StaticSource
from agent.briefing.store import BriefingStore, load_schema_sql
from agent.permission.gateway import SecurityGateway
from agent.protocol.cancel import AgentCancelledError
from agent.tools.briefing.briefing_tool import BriefingTool
from agent.tools.tool_manager import ToolManager
from application import Application

check_tool_call = SecurityGateway.check


class ScriptedModel:
    model = "test-model"

    def __init__(self, incomplete=False):
        self.requests = []
        self.incomplete = incomplete

    def call_stream(self, request):
        self.requests.append(request)
        last = request.messages[-1]["content"]
        if any(block.get("type") == "tool_result" for block in last):
            yield {"choices": [{"delta": {"content": "已完成"}, "finish_reason": "stop"}]}
            return
        text = next(block["text"] for block in last if block["type"] == "text")
        data = json.loads(text[text.index("{"):])
        tool_names = {tool["name"] for tool in request.tools}
        assert tool_names <= {"briefing_decisions_result", "briefing_body_result", "read_briefing_source"}
        if "candidates" in data:
            rows = data["candidates"]
            if self.incomplete:
                rows = rows[:-1]
            arguments = {"decisions": [{
                "id": row["id"], "selected": not row["sender_email"].endswith("@promo.example"),
                "reason": "发件地址匹配排除后缀" if row["sender_email"].endswith("@promo.example") else "课程通知需要关注",
                "section": "action", "score": 90, "summary": f"Agent 摘要：{row['title']}，请查看课程要求。",
            } for row in rows]}
            name = "briefing_decisions_result"
        else:
            arguments = {"body": "## Agent 撰写的课程简报\n" + "\n".join(f"- {row['summary']}" for row in data["items"]),
                         "source_item_ids": [row["id"] for row in data["items"]],
                         "reports": [{"id": row["id"], "content": f"完整分析：{row['summary']}"} for row in data["items"]]}
            name = "briefing_body_result"
        yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"call-{len(self.requests)}",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}, "finish_reason": "tool_calls"}]}


@pytest.fixture
def service(tmp_path):
    return BriefingService(BriefingStore(tmp_path / "briefing.db"))


def item(key, address="noreply@school.example", **changes):
    return FetchedItem(source="email", source_id=key, sender="课程系统", sender_email=address,
        title=key, occurred_at="2026-09-08T23:00:00Z", payload={"body": "课程作业通知"}, **changes)


def pipeline(service, model, items=(), at="2026-09-09T08:00:00+08:00", cursor="9"):
    return BriefingPipeline(service, [StaticSource(list(items), cursors={"imap_uid": cursor})],
        clock=lambda: datetime.fromisoformat(at), generator=AgentBriefingGenerator(model=model))


def test_pipeline_accepts_application_briefing_port(service, monkeypatch):
    monkeypatch.setattr("agent.briefing.service.BriefingService", lambda: service)
    port = Application.port("briefing")
    detail = pipeline(port, ScriptedModel(), [item("课程")]).run()
    assert detail["briefing"].status == "completed"
    assert detail["items"][0].title == "课程"


def test_agent_reads_markdown_rules_and_writes_all_batches(service):
    text = "# 筛选\n排除发件地址以 @promo.example 结尾的邮件。\n# 简报\n保留课程通知，写清下一步行动。"
    service.create_rule({"text": text})
    model = ScriptedModel()
    detail = pipeline(service, model, [*[item(f"课程-{i}") for i in range(47)], item("促销", "bot@promo.example")]).run()
    assert detail["briefing"].status == "completed"
    assert detail["briefing"].fetched_count == 48
    assert detail["briefing"].kept_count == len(detail["items"]) == 47
    assert detail["briefing"].filtered_count == 1
    assert all("Agent 摘要" in row.snippet for row in detail["items"])
    assert all(row.payload.get("_briefing_reason") == "课程通知需要关注" for row in detail["items"])
    assert all("完整分析" in row.payload.get("_briefing_report", "") for row in detail["items"])
    assert detail["briefing"].body.count("Agent 摘要") == 47
    assert "@promo.example" in detail["briefing"].rule_text
    assert all(text in request.system for request in model.requests)
    report_requests = [request for request in model.requests if any(tool['name'] == 'briefing_body_result' for tool in request.tools)]
    assert report_requests
    for request in report_requests:
        prompt = next(block['text'] for message in request.messages for block in message['content']
                      if block['type'] == 'text' and '依据规则撰写' in block['text'])
        assert '完整报告' in prompt and '3至5行精简概览' not in prompt
        assert any(tool['name'] == 'read_briefing_source' for tool in request.tools)
        assert all(row['body_preview'] == '课程作业通知' for row in json.loads(prompt[prompt.index('{'):])['items'])
    assert any(row["filter_reason"] == "发件地址匹配排除后缀" for row in detail["mail"])
    assert service.get_revision(detail["briefing"].id, 1)["briefing"]["rule_text"] == detail["briefing"].rule_text
    assert service.get_cursor("email", "default", "imap_uid").cursor_value == "9"


def test_incomplete_agent_result_keeps_previous_snapshot_and_cursor(service):
    first = pipeline(service, ScriptedModel(), [item("课程")]).run()
    service.create_rule({"text": "新规则：保留课程信息。"})
    with pytest.raises(ValueError, match="未提交完整结果"):
        pipeline(service, ScriptedModel(incomplete=True), [item("新增")], at="2026-09-09T15:00:00+08:00", cursor="99").run(operation="update")
    failed = service.get_briefing(first["briefing"].id)
    for key in ("body", "window_start", "window_end", "rule_text", "kept_count"):
        assert getattr(failed["briefing"], key) == getattr(first["briefing"], key)
    assert failed["briefing"].status == "failed"
    assert failed["items"] == first["items"]
    assert failed["mail"] == first["mail"]
    assert service.get_cursor("email", "default", "imap_uid").cursor_value == "9"


def test_thread_card_keeps_each_agents_summary(service):
    model = ScriptedModel()
    detail = pipeline(service, model, [item("原通知"), item("修订通知", thread_id="原通知")]).run()
    assert detail["briefing"].kept_count == 2
    assert len(detail["items"]) == 1
    assert "原通知" in detail["items"][0].snippet
    assert "修订通知" in detail["items"][0].snippet
    assert "原通知" in detail["briefing"].body and "修订通知" in detail["briefing"].body
    members = detail["items"][0].payload["_briefing_members"]
    assert {row["title"] for row in members} == {"原通知", "修订通知"}
    assert all(row["body"] == "课程作业通知" for row in members)
    assert all(row["reason"] == "课程通知需要关注" for row in members)
    report_request = next(request for request in model.requests if any(tool["name"] == "briefing_body_result" for tool in request.tools))
    report_prompt = next(block["text"] for message in report_request.messages for block in message["content"]
                         if block["type"] == "text" and "依据规则撰写" in block["text"])
    prompt_members = json.loads(report_prompt[report_prompt.index("{"):])["items"][0]["members"]
    assert {row["id"] for row in prompt_members} == {row["id"] for row in members}


@pytest.mark.parametrize("items", [[], [item("广告", "bot@promo.example")]])
def test_empty_and_all_filtered_windows_still_use_agent_for_body(service, items):
    model = ScriptedModel()
    detail = pipeline(service, model, items).run()
    assert detail["items"] == []
    assert detail["briefing"].kept_count == 0
    assert "Agent 撰写" in detail["briefing"].body
    assert model.requests


def test_tool_supports_markdown_rules_and_uses_calling_agents_model(service, monkeypatch):
    tool = BriefingTool(service=service)
    tool.model = ScriptedModel()
    added = tool.execute({"action": "add_rule", "text": "# 保留\n保留课程通知。"})
    assert added.status == "success"
    assert "# 保留" in tool.execute({"action": "list_rules"}).result
    monkeypatch.setattr("agent.briefing.settings.email_sources", lambda: [StaticSource([item("课程")])])
    monkeypatch.setattr("agent.briefing.pipeline._now", lambda: datetime.fromisoformat("2026-09-09T08:00:00+08:00"))
    result = tool.execute({"action": "run"})
    assert result.status == "success"
    assert "Agent 撰写" in result.result
    mailbox = json.loads(tool.execute({"action": "mail", "briefing_id": "brf-2026-09-09-morning", "category": "selected"}).result)
    assert mailbox["total"] == 1
    row = mailbox["mail"][0]
    full = json.loads(tool.execute({"action": "mail", "briefing_id": "brf-2026-09-09-morning", "source_item_id": row["id"]}).result)
    assert full["body"] == "课程作业通知"
    assert tool.model.requests


def test_decision_request_states_every_id_and_hard_rule_before_submission(service):
    model = ScriptedModel()
    pipeline = BriefingPipeline(service, [StaticSource([item("course"), item("notice")])], generator=AgentBriefingGenerator(model=model))
    pipeline.run(briefing_date="2026-09-09")
    texts = [block.get("text", "") for request in model.requests for message in request.messages
             for block in (message["content"] if isinstance(message["content"], list) else [])
             if isinstance(block, dict)]
    text = next(value for value in texts if "expected_ids" in value)
    payload = json.loads(text[text.index("{"):])
    ids = [row["id"] for row in payload["candidates"]]
    assert "expected_ids: " + json.dumps(ids, ensure_ascii=False) in text
    for rule in ("不能遗漏、重复或加入未知 ID", "selected 必须是布尔值", "reason 必须是非空字符串",
                 "selected 为 false", "section 必须是 action 或 fyi", "score 必须是 0 至 100 的整数",
                 "summary 必须是非空字符串", "category", "information_type"):
        assert rule in text
    schema = next(tool["input_schema"] for request in model.requests for tool in request.tools
                  if tool["name"] == "briefing_decisions_result")
    item_schema = schema["properties"]["decisions"]["items"]
    assert item_schema["required"] == ["id", "selected", "reason"]
    assert item_schema["allOf"][0]["then"]["required"] == ["section", "score", "summary"]
    assert decision_schema()["properties"]["decisions"]["items"]["required"] == item_schema["required"]
    excluded = validate_decisions({"decisions": [
        {"id": ids[0], "selected": False, "reason": "排除"},
        {"id": ids[1], "selected": True, "reason": "保留", "section": "fyi", "score": 10, "summary": "摘要"},
    ]}, ids)
    assert excluded is None
    rejected = ResultTool("result", {}, lambda data: validate_decisions(data, ids)).execute(
        {"decisions": [
            {"id": ids[0], "selected": True, "reason": "保留"},
            {"id": ids[1], "selected": False, "reason": "排除"},
        ]})
    assert rejected.status == "error"
    assert ids[0] in rejected.result and "section" in rejected.result
    assert "body" not in rejected.result


def test_result_tools_reject_unknown_missing_duplicate_and_bad_values():
    valid = {"decisions": [{"id": "a", "selected": True, "reason": "important", "section": "action", "score": 90, "summary": "Task"}]}
    tool = ResultTool("result", {}, lambda data: validate_decisions(data, ["a"]))
    for payload in ({"decisions": []}, {"decisions": valid["decisions"] * 2},
                    {"decisions": [{**valid["decisions"][0], "id": "unknown"}]},
                    {"decisions": [{**valid["decisions"][0], "selected": "true"}]},
                    {"decisions": [{**valid["decisions"][0], "score": True}]}):
        assert tool.execute(payload).status == "error"
        assert tool.submission is None
    assert tool.execute(valid).status == "success"
    with pytest.raises(ValueError):
        validate_body({"body": "draft", "source_item_ids": []}, ["a"])
    with pytest.raises(ValueError, match="逐条"):
        validate_body({"body": "draft", "source_item_ids": ["a"]}, ["a"])
    with pytest.raises(ValueError, match="具体内容"):
        validate_body({"body": "draft", "source_item_ids": ["a"],
                       "reports": [{"id": "a", "content": " "}]}, ["a"])


def test_full_source_read_is_paged_and_confined_to_this_batch():
    tool = ReadSourceTool([{"id": "a", "body": "x" * 18000}])
    first = json.loads(tool.execute({"id": "a"}).result)
    assert len(first["body"]) == first["next_offset"] == 8000
    last = json.loads(tool.execute({"id": "a", "offset": 16000}).result)
    assert len(last["body"]) == 2000 and last["next_offset"] is None
    assert tool.execute({"id": "other-account"}).status == "error"
    assert tool.execute({"id": "a", "offset": -1}).status == "error"


def test_cancelled_generation_does_not_call_model():
    event = threading.Event()
    event.set()
    generator = AgentBriefingGenerator(model=ScriptedModel(), cancel_event=event)
    with pytest.raises(AgentCancelledError):
        generator.generate([], [], briefing_date="2026-09-09", kind="morning", window_start="a", window_end="b")
    assert generator.model.requests == []


def test_fixed_agent_tools_are_not_replaced_by_mcp():
    agent = BriefingAgent(system_prompt="private task", model=ScriptedModel(), enable_skills=False)
    assert agent.get_full_system_prompt() == "private task"
    manager = ToolManager()
    assert manager.sync_mcp_into_agent(agent) == ([], [])
    assert agent.tools == []


def test_agent_partial_update_reuses_other_sources_decisions_and_snapshot_content(service):
    email = StaticSource([item("邮件")])
    original = FetchedItem(source="elearning", source_id="announcement:1", title="原课程公告",
        occurred_at="2026-09-08T23:00:00Z", payload={"body": "原课程公告正文"})
    canvas = StaticSource([original], name="elearning")
    first_model = ScriptedModel()
    def at():
        return datetime.fromisoformat("2026-09-09T08:00:00+08:00")
    first = BriefingPipeline(service, [email, canvas], clock=at,
        generator=AgentBriefingGenerator(model=first_model)).run()
    old_snapshot = next(row for row in first["mail"] if row["source"] == "elearning")
    old_card = next(row for row in first["items"] if row.source == "elearning")
    service.update_item_status(old_card.id, "done")
    # Catalog changes from another/failed run must not leak into an unselected
    # source's frozen candidate or card metadata.
    service.upsert_source_item(FetchedItem(source="elearning", source_id="announcement:1",
        title="尚未同步的标题", occurred_at="2026-09-09T03:00:00Z", payload={"body": "尚未同步的正文"}).to_catalog_payload())
    canvas.fetch = lambda cursors: pytest.fail("unselected source must not fetch")
    model = ScriptedModel()
    result = BriefingPipeline(service, [email, canvas],
        clock=lambda: datetime.fromisoformat("2026-09-09T15:00:00+08:00"),
        generator=AgentBriefingGenerator(model=model)).run(operation="update", sources=["email"])
    new_snapshot = next(row for row in result["mail"] if row["source"] == "elearning")
    assert new_snapshot["decision"] == old_snapshot["decision"]
    assert new_snapshot["title"] == "原课程公告" and new_snapshot["body"] == "原课程公告正文"
    card = next(row for row in result["items"] if row.source == "elearning")
    assert card.title == old_card.title and card.payload["body"] == old_card.payload["body"]
    assert card.status == "done" and card.id == old_card.id
    assert result["briefing"].status == "completed"
    for request in model.requests:
        text = next((part.get("text", "") for part in request.messages[-1]["content"] if part.get("type") == "text"), "")
        if "\"candidates\"" in text:
            data = json.loads(text[text.index("{"):])
            assert {row["source"] for row in data["candidates"]} == {"email"}


def test_manual_and_tool_factories_use_agent_generator(service, monkeypatch):
    from channel.desktop.desktop_channel import _briefing_pipeline
    monkeypatch.setattr("agent.briefing.settings.email_sources", lambda path=None: [])
    tool = BriefingTool(service=service)
    tool.model = ScriptedModel()
    assert isinstance(_briefing_pipeline(service).generator, AgentBriefingGenerator)
    assert tool._get_pipeline(service).generator.model is tool.model


def test_briefing_tool_is_discoverable_and_permission_actions_are_correct():
    manager = ToolManager()
    manager._load_tools_from_init()
    assert "briefing" in manager.tool_classes
    assert manager.tool_classes["briefing"] is BriefingTool
    assert "text" in BriefingTool.params["properties"]
    assert "match_field" not in BriefingTool.params["properties"]
    for action in ("get", "list", "mail", "list_rules"):
        assert check_tool_call("read-only", "briefing", {"action": action})
    for action in ("run", "add_rule", "update_rule", "delete_rule", "item_status"):
        assert not check_tool_call("read-only", "briefing", {"action": action})
        assert check_tool_call("workspace-write", "briefing", {"action": action})


def test_markdown_rules_crud_and_legacy_migration(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    sql = load_schema_sql().replace("    text             TEXT    NOT NULL DEFAULT '',              -- free-form filtering and writing instructions\n", "")
    conn.executescript(sql)
    conn.execute("INSERT INTO filter_rules (id,source,action,match_field,match_op,match_value,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("old", "email", "exclude", "sender_domain", "eq", "spam.example", "old rule", "a", "a"))
    conn.commit()
    conn.close()
    service = BriefingService(BriefingStore(path))
    assert "排除发件域名等于“spam.example”" in service.get_rule("old").text
    saved = service.create_rule({"text": DEFAULT_RULE_TEXT})
    assert saved.text == DEFAULT_RULE_TEXT.strip()
    changed = service.update_rule(saved.id, {"text": "请排除标题以广告结尾的信息。", "enabled": False})
    assert changed.text == "请排除标题以广告结尾的信息。" and changed.enabled is False
    assert saved.id not in {row.id for row in service.list_rules(enabled_only=True)}
    service.delete_rule(saved.id)
    for text in ("", "   ", None, {"instruction": "x"}):
        with pytest.raises(ValueError, match="文稿"):
            service.create_rule({"text": text})
