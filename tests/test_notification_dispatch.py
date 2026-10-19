"""Durable, bounded notification delivery across scheduler restarts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import requests

from agent.scheduler.automation_store import AutomationStore
from agent.scheduler.dispatch import dispatch_notification
from agent.scheduler import integration
from agent.scheduler.dispatch import DeliveryOutcome
from agent.scheduler import delivery
from bridge.reply import Reply, ReplyType
from bridge.context import Context, ContextType


def _store(tmp_path):
    store = AutomationStore(tmp_path / "scheduler" / "tasks.json", "agent-a")
    store.add_task({"id": "scheduled", "name": "Scheduled", "enabled": True,
                    "action": {"type": "send_message", "content": "Saved"}})
    return store


def _route(enabled=False):
    route = {"primary": {"channel_type": "telegram", "receiver": "100", "is_group": False}}
    if enabled:
        route["backup_enabled"] = True
        route["backup"] = {"channel_type": "desktop", "receiver": "client", "is_group": False}
    return route


def test_platform_acceptance_has_separate_persisted_recipient_and_attempt(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    sent = []
    channel = SimpleNamespace(send=lambda reply, context: sent.append((reply.content, context["receiver"]))
                              or {"success": True, "ret": 0, "message_id": "m-1", "context_token": "secret"})
    result = dispatch_notification(store, job_id, _route(), "Saved", channel_provider=lambda _: channel)
    assert result.status == "accepted"
    record = store.get_delivery(job_id, "primary")
    assert record["status"] == "accepted" and record["attempts"] == 1
    assert record["receiver"] == "100" and record["platform_response"]["message_id"] == "m-1"
    assert "secret" not in str(record)
    assert sent == [("Saved", "100")]
    assert store.latest_delivery("scheduled")["status"] == "accepted"
    assert store.latest_delivery("scheduled")["channel_type"] == "telegram"
    assert store.latest_delivery("other") is None


def test_failed_proactive_send_does_not_repeat_or_switch_channel(tmp_path, caplog):
    from common.log import logger

    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    calls = []
    def expired(*_args):
        calls.append(1)
        raise RuntimeError("platform rejected the chat")
    channel = SimpleNamespace(send=expired)
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("WARNING", logger=logger.name):
            first = dispatch_notification(store, job_id, _route(True), "Saved",
                                          channel_provider=lambda _: channel)
            second = dispatch_notification(store, job_id, _route(True), "Saved",
                                           channel_provider=lambda _: channel)
    finally:
        logger.removeHandler(caplog.handler)
    assert first.status == second.status == "failed"
    assert len(calls) == 1
    assert store.get_delivery(job_id, "backup") is None
    assert "Delivery" in caplog.text and "failed" in caplog.text
    assert "platform rejected the chat" in caplog.text


def test_transient_error_retries_only_three_times_and_uses_saved_job(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    calls = []
    def transient(*_args):
        calls.append(1)
        raise requests.exceptions.ConnectTimeout("could not connect")
    channel = SimpleNamespace(send=transient)
    results = [dispatch_notification(store, job_id, _route(), "Saved", channel_provider=lambda _: channel)
               for _ in range(4)]
    assert [item.status for item in results] == ["failed"] * 4
    assert [item.retryable for item in results] == [True, True, False, False]
    assert len(calls) == 3


def test_connection_reset_after_server_acceptance_is_unknown_and_never_falls_back(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    calls = []
    def lost_response(*_args):
        calls.append("primary")
        raise requests.exceptions.ConnectionError("connection reset after send")
    result = dispatch_notification(store, job_id, _route(True), "Saved",
                                   channel_provider=lambda name: SimpleNamespace(send=lost_response if name == "telegram"
                                       else lambda *_args: calls.append("backup")))
    assert result.status == "unknown" and calls == ["primary"]
    assert store.get_delivery(job_id, "primary")["status"] == "unknown"
    assert store.get_delivery(job_id, "backup") is None


def test_unknown_timeout_never_blindly_retries_or_uses_backup(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    calls = []
    def timeout(*_args):
        calls.append("primary")
        raise requests.exceptions.Timeout("response lost")
    result = dispatch_notification(store, job_id, _route(True), "Saved",
                                   channel_provider=lambda name: SimpleNamespace(send=timeout if name == "telegram"
                                       else lambda *_args: calls.append("backup")))
    assert result.status == "unknown"
    assert calls == ["primary"]
    assert store.get_delivery(job_id, "backup") is None
    dispatch_notification(store, job_id, _route(True), "Saved",
                          channel_provider=lambda _: SimpleNamespace(send=timeout))
    assert calls == ["primary"]


def test_backup_dispatch_requires_saved_opt_in_and_explicit_failure(tmp_path):
    store = _store(tmp_path)
    sends = []
    def provider(name):
        def send(*_args):
            sends.append(name)
            return name == "feishu"
        return SimpleNamespace(send=send)
    first = store.claim_occurrence("scheduled", manual=True)
    assert dispatch_notification(store, first, _route(False), "Saved", channel_provider=provider).status == "failed"
    assert sends == ["telegram"]
    second = store.claim_occurrence("scheduled", manual=True)
    assert dispatch_notification(store, second, _route(True), "Saved", channel_provider=provider).status == "failed"
    assert sends == ["telegram", "telegram"]
    assert store.get_delivery(second, "backup") is None


def test_restart_and_expiry_do_not_resend(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    assert store.begin_delivery(job_id, "primary", "weixin", "wx_user") == "send"
    with store._connect() as db:
        db.execute("UPDATE job_deliveries SET updated_at=? WHERE job_run_id=?",
                   ("2000-01-01T00:00:00+00:00", job_id))
    reopened = AutomationStore(tmp_path / "scheduler" / "tasks.json", "agent-a")
    sends = []
    result = dispatch_notification(reopened, job_id, _route(), "Saved",
                                   channel_provider=lambda _: SimpleNamespace(send=lambda *_args: sends.append(1)))
    assert result.status == "unknown" and not sends
    expired_job = reopened.claim_occurrence("scheduled", manual=True)
    result = dispatch_notification(reopened, expired_job, _route(), "Saved",
                                   expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                                   channel_provider=lambda _: SimpleNamespace(send=lambda *_args: sends.append(1)))
    assert result.status == "expired" and not sends
    assert reopened.get_delivery(expired_job, "primary")["status"] == "expired"


def test_accepted_delivery_keeps_its_result_after_expiry(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    sends = []
    channel = SimpleNamespace(send=lambda *_args: sends.append(1) or True)
    assert dispatch_notification(store, job_id, _route(), "Saved",
                                 channel_provider=lambda _: channel).status == "accepted"
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert dispatch_notification(store, job_id, _route(), "Saved", expires_at=past,
                                 channel_provider=lambda _: channel).status == "accepted"
    assert sends == [1]
    assert store.get_delivery(job_id, "primary")["status"] == "accepted"


def test_saved_execution_can_resume_delivery_after_crash(tmp_path):
    store = _store(tmp_path)
    scheduled = datetime.now(timezone.utc).isoformat()
    job_id = store.claim_occurrence("scheduled", scheduled_at=scheduled, lease_seconds=1)
    path = tmp_path / "saved-output.txt"
    path.write_text("finished work")
    store.record_execution_ref(job_id, path)
    with store._connect() as db:
        db.execute("UPDATE job_runs SET lease_until=? WHERE job_run_id=?",
                   ("2000-01-01T00:00:00+00:00", job_id))
    reopened = AutomationStore(tmp_path / "scheduler" / "tasks.json", "agent-a")
    assert reopened.claim_occurrence("scheduled", scheduled_at=scheduled) == job_id
    assert reopened.get_execution_ref(job_id) == str(path)


def test_failed_delivery_expires_with_recorded_status(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    channel = SimpleNamespace(send=lambda *_args: False)
    assert dispatch_notification(store, job_id, _route(), "Saved",
                                 channel_provider=lambda _: channel).status == "failed"
    assert dispatch_notification(store, job_id, _route(), "Saved",
                                 expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                                 channel_provider=lambda _: channel).status == "expired"
    assert store.get_delivery(job_id, "primary")["status"] == "expired"


def test_parallel_duplicate_send_does_not_change_inflight_state(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    assert store.begin_delivery(job_id, "primary", "weixin", "wx_user") == "send"
    assert store.begin_delivery(job_id, "primary", "weixin", "wx_user") == "sending"
    assert store.get_delivery(job_id, "primary")["status"] == "sending"
    store.finish_delivery(job_id, "primary", "accepted")
    assert store.get_delivery(job_id, "primary")["status"] == "accepted"


def test_pending_delivery_can_resume_after_restart_before_send(tmp_path):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    store.queue_delivery(job_id, "primary", "weixin", "wx_user")
    assert store.get_delivery(job_id, "primary")["status"] == "pending"
    reopened = AutomationStore(tmp_path / "scheduler" / "tasks.json", "agent-a")
    sent = []
    result = dispatch_notification(reopened, job_id, _route(), "Saved",
                                   channel_provider=lambda _: SimpleNamespace(send=lambda *_args: sent.append(1) or True))
    assert result.status == "accepted" and sent == [1]
    assert reopened.get_delivery(job_id, "primary")["attempts"] == 1


def test_weixin_scheduled_text_exposes_platform_acceptance(monkeypatch):
    from channel.weixin.weixin_channel import WeixinChannel
    channel = WeixinChannel()
    channel._context_tokens = {"wx_user": "private-token"}
    channel.api = SimpleNamespace(send_text=lambda *_args: {"ret": 0, "msg_id": "wx-1"})
    context = Context(ContextType.TEXT, "Hello")
    context["receiver"] = "wx_user"
    context["scheduled_delivery"] = True
    response = channel.send(Reply(ReplyType.TEXT, "Hello"), context)
    assert response["ret"] == 0 and response["msg_id"] == "wx-1"


def test_feishu_scheduled_text_exposes_platform_acceptance(monkeypatch):
    from channel.feishu.feishu_channel import FeiShuChanel
    from channel.feishu import feishu_channel
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"message_id": "fs-1"}}
    monkeypatch.setattr(feishu_channel.requests, "post", lambda **_kwargs: FakeResponse())
    channel = FeiShuChanel()
    monkeypatch.setattr(channel, "fetch_access_token", lambda: "test-token")
    context = Context(ContextType.TEXT, "Hello")
    context["receiver"] = "ou_student"
    context["isgroup"] = False
    context["scheduled_delivery"] = True
    response = channel.send(Reply(ReplyType.TEXT, "Hello"), context)
    assert response["code"] == 0 and response["data"]["message_id"] == "fs-1"


def test_scheduled_agent_output_survives_delivery_retry(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job_id = store.claim_occurrence("scheduled", manual=True)
    calls = []
    bridge = SimpleNamespace(agent_reply=lambda *_args, **_kwargs: calls.append("agent") or
                             Reply(ReplyType.TEXT, "finished work"))
    channel = SimpleNamespace(send=lambda *_args: (_ for _ in ()).throw(
        requests.exceptions.ConnectTimeout("offline before connect")))
    monkeypatch.setattr(integration, "get_task_store", lambda **_kwargs: store)
    monkeypatch.setattr("agent.scheduler.result_cache.runs_dir", lambda **_kwargs: tmp_path)
    monkeypatch.setattr("agent.scheduler.dispatch._channel_for", lambda _: channel)
    monkeypatch.setattr(integration, "_remember_delivered_output", lambda *_args: True)
    task = {"id": "scheduled", "job_run_id": job_id,
            "action": {"type": "agent_task", "task_description": "Finish work",
                       "channel_type": "weixin", "receiver": "wx_user"},
            "notification_route": _route()}
    assert integration._execute_agent_task(task, bridge, "agent-a") is False
    assert store.get_delivery(job_id, "primary")["status"] == "failed"
    channel.send = lambda *_args: True
    assert integration._execute_agent_task(task, bridge, "agent-a") is True
    assert calls == ["agent"]
    assert store.get_delivery(job_id, "primary")["status"] == "accepted"


def test_scheduler_todo_command_reports_external_delivery_waiting(monkeypatch):
    from application import Application
    calls = []
    monkeypatch.setattr(Application, "command", lambda *_args: {"operation_id": "queued"})
    monkeypatch.setattr(Application, "dispatch_todo_reminder", staticmethod(
        lambda todo_id, due, context: calls.append((todo_id, due, context.source)) or
        DeliveryOutcome("waiting", "Weixin session expired")), raising=False)
    task = {"id": "todo-reminder:one", "job_run_id": "job-one",
            "action": {"type": "application_command", "domain": "todos", "command": "QueueTodoReminder",
                       "params": ["one", "2026-10-09T06:00:00+00:00"]}}
    outcome = integration._execute_application_command(task, "agent-a")
    assert outcome is False
    assert calls == [("one", "2026-10-09T06:00:00+00:00", "scheduler")]


def _scheduler_context():
    from application import RequestContext

    return RequestContext(source="scheduler", user_id="test-user", agent_id="test-agent", session_id="s")


# Delivered-once and late-expiry todo reminders run against the real plugin outbox in
# tests/test_todos_plugin_gateway.py; route edits below use the same real-worker path.


def test_todo_route_edit_replaces_waiting_recipient_for_same_instant(todos_plugin, monkeypatch):
    from application import Application
    monkeypatch.setattr(delivery, "runtime_channel", lambda _: SimpleNamespace(
        login_status="logged_in", _context_tokens={"wx_user": "private-token"}))
    sends = []
    def provider(name):
        def send(*_args):
            sends.append(name)
            if name == "telegram":
                raise RuntimeError("platform rejected the chat")
            return True
        return SimpleNamespace(send=send)
    monkeypatch.setattr("agent.scheduler.dispatch._channel_for", provider)
    service = todos_plugin
    due = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(microsecond=0).isoformat()
    todo = service.create_todo({"title": "Submit", "remind_at": due, "reminder_delivery": _route()})
    service.queue_scheduled_reminder(todo["id"], due)
    assert Application.dispatch_todo_reminder(todo["id"], due, _scheduler_context()).status == "failed"
    service.update_todo(todo["id"], {"reminder_delivery": {
        "primary": {"channel_type": "wecom_bot", "receiver": "chat-1"}}})
    service.queue_scheduled_reminder(todo["id"], due)
    assert Application.dispatch_todo_reminder(todo["id"], due, _scheduler_context()).status == "accepted"
    assert sends == ["telegram", "wecom_bot"]


def test_todo_unknown_result_is_preserved_across_route_edit(todos_plugin, monkeypatch):
    from application import Application
    monkeypatch.setattr(delivery, "runtime_channel", lambda _: SimpleNamespace(
        login_status="logged_in", _context_tokens={"wx_user": "private-token"}))
    sends = []
    def send(*_args):
        sends.append(1)
        raise requests.exceptions.Timeout("response lost")
    monkeypatch.setattr("agent.scheduler.dispatch._channel_for", lambda _: SimpleNamespace(send=send))
    service = todos_plugin
    due = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(microsecond=0).isoformat()
    todo = service.create_todo({"title": "Submit", "remind_at": due, "reminder_delivery": _route()})
    service.queue_scheduled_reminder(todo["id"], due)
    assert Application.dispatch_todo_reminder(todo["id"], due, _scheduler_context()).status == "unknown"
    service.update_todo(todo["id"], {"reminder_delivery": {
        "primary": {"channel_type": "wecom_bot", "receiver": "chat-1"}}})
    service.queue_scheduled_reminder(todo["id"], due)
    assert Application.dispatch_todo_reminder(todo["id"], due, _scheduler_context()).status == "unknown"
    assert service.get_todo(todo["id"])["reminder_delivery_status"]["status"] == "unknown"
    assert sends == [1]
