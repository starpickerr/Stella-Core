"""Queued turns survive a process exit without corrupting transcript order."""

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from agent.memory.conversation_store import ConversationStore
from agent.runtime.run_record import RunRecord
from agent.runtime.session_run import SessionRun
from bridge.agent_bridge import AgentBridge
from bridge.context import Context
from bridge.reply import Reply, ReplyType


def _user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _assistant(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _bridge(tmp_path, monkeypatch, on_run, on_get=None):
    history = ConversationStore(tmp_path / "history.db")
    real_record = RunRecord
    monkeypatch.setattr(
        "agent.runtime.run_record.RunRecord",
        lambda: real_record(tmp_path / "runs.db"),
    )
    def get_agent(session_id=None, agent_id=None):
        loaded = history.load_messages(session_id)
        if on_get is not None:
            on_get(loaded)
        return loaded

    bridge = SimpleNamespace(
        agent_registry=SimpleNamespace(default_agent_id="default"),
        _session_run=SessionRun(),
        route_context=lambda _context: "default",
        get_conversation_store=lambda _agent_id=None: history,
        get_agent=get_agent,
        _agent_reply_impl=on_run,
    )
    return bridge, history


def test_admission_journal_holds_input_before_it_enters_history(tmp_path):
    history = ConversationStore(tmp_path / "history.db")
    history.queue_user_message(
        "s", _user("second"), run_id="r2", request_id="request-2",
        channel_type="web", clear_history=True,
    )
    assert history.load_messages("s") == []
    queued = history.list_run_admissions("s")
    assert queued[0]["user_content"] == _user("second")["content"]
    assert queued[0]["request_id"] == "request-2"
    assert queued[0]["run_id"] == "r2"
    assert queued[0]["status"] == "queued"
    assert queued[0]["clear_history"] is True
    reopened = ConversationStore(tmp_path / "history.db")
    assert reopened.list_run_admissions("s")[0]["status"] == "queued"
    assert reopened.load_messages("s") == []  # no automatic replay to the model

    history.start_run_admission("r2")
    assert [message["role"] for message in history.load_messages("s")] == ["user"]
    with pytest.raises(ValueError, match="no queued user admission"):
        history.start_run_admission("r2")
    assert len(history.load_messages("s")) == 1


def test_existing_admission_rows_migrate_without_losing_audit_data(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE run_admissions (
               run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
               request_id TEXT, user_seq INTEGER NOT NULL,
               status TEXT NOT NULL DEFAULT 'queued', created_at INTEGER NOT NULL)"""
        )
        conn.execute(
            """INSERT INTO run_admissions
               (run_id,session_id,request_id,user_seq,status,created_at)
               VALUES ('legacy','s','old-request',4,'completed',1)"""
        )
    history = ConversationStore(path)
    row = history.list_run_admissions("s")[0]
    assert row["run_id"] == "legacy"
    assert row["request_id"] == "old-request"
    assert row["user_seq"] == 4
    assert row["status"] == "completed"
    assert row["user_content"] is None


def test_deleting_a_session_discards_its_queued_input(tmp_path):
    history = ConversationStore(tmp_path / "history.db")
    history.queue_user_message("s", _user("private input"), run_id="r1")
    history.clear_session("s")
    assert history.list_run_admissions("s") == []
    with pytest.raises(ValueError, match="no queued user admission"):
        history.start_run_admission("r1")


def test_second_input_is_durable_while_first_run_holds_session_lock(tmp_path, monkeypatch):
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    loaded_before_turn = []
    history = None

    def on_run(query, context, on_event, clear_history, pre_persisted_user=False):
        assert pre_persisted_user
        if query == "first":
            first_started.set()
            assert release_first.wait(3)
        else:
            second_started.set()
        history.append_messages("s", [_assistant(query + " reply")], create_if_missing=False)
        return Reply(ReplyType.TEXT, query + " reply")

    bridge, history = _bridge(
        tmp_path, monkeypatch, on_run,
        on_get=lambda messages: loaded_before_turn.append(
            [message["content"][0]["text"] for message in messages]
        ),
    )
    replies = []

    def invoke(query):
        context = {"session_id": "s", "request_id": query, "channel_type": "web"}
        replies.append(AgentBridge.agent_reply(bridge, query, context))

    first = threading.Thread(target=invoke, args=("first",))
    second = threading.Thread(target=invoke, args=("second",))
    first.start()
    assert first_started.wait(3)
    second.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            rows = history.list_run_admissions("s")
            if any(row["request_id"] == "second" and row["status"] == "queued" for row in rows):
                break
            time.sleep(0.01)
        else:
            pytest.fail("second input was not durably admitted while queued")
        assert not second_started.is_set()
        assert [message["role"] for message in history.load_messages("s")] == ["user"]
    finally:
        release_first.set()
        first.join(3)
        second.join(3)

    assert not first.is_alive() and not second.is_alive()
    assert [reply.type for reply in replies] == [ReplyType.TEXT, ReplyType.TEXT]
    messages = history.load_messages("s")
    assert [message["role"] for message in messages] == [
        "user", "assistant", "user", "assistant",
    ]
    assert [message["content"][0]["text"] for message in messages] == [
        "first", "first reply", "second", "second reply",
    ]
    assert loaded_before_turn == [[], ["first", "first reply"]]


def test_queued_clear_history_waits_for_the_active_run(tmp_path, monkeypatch):
    first_started = threading.Event()
    release_first = threading.Event()
    history = None

    def on_run(query, context, on_event, clear_history, pre_persisted_user=False):
        assert pre_persisted_user
        if query == "first":
            first_started.set()
            assert release_first.wait(3)
        history.append_messages("s", [_assistant(query + " reply")], create_if_missing=False)
        return Reply(ReplyType.TEXT, query + " reply")

    bridge, history = _bridge(tmp_path, monkeypatch, on_run)
    first = threading.Thread(target=lambda: AgentBridge.agent_reply(
        bridge, "first", {"session_id": "s", "request_id": "r1"}
    ))
    second = threading.Thread(target=lambda: AgentBridge.agent_reply(
        bridge, "second", {"session_id": "s", "request_id": "r2"}, clear_history=True
    ))
    first.start()
    assert first_started.wait(3)
    second.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(row["request_id"] == "r2" for row in history.list_run_admissions("s")):
                break
            time.sleep(0.01)
        else:
            pytest.fail("clear-history input was not admitted")
        assert [message["content"][0]["text"] for message in history.load_messages("s")] == ["first"]
    finally:
        release_first.set()
        first.join(3)
        second.join(3)
    assert [message["content"][0]["text"] for message in history.load_messages("s")] == [
        "second", "second reply",
    ]


def test_admission_failure_does_not_start_the_agent(tmp_path, monkeypatch):
    called = []
    bridge, history = _bridge(tmp_path, monkeypatch, lambda *_args, **_kwargs: called.append(True))

    def fail(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(history, "queue_user_message", fail)
    reply = AgentBridge.agent_reply(
        bridge, "input", {"session_id": "s", "request_id": "r1"}
    )
    assert reply.type == ReplyType.ERROR
    assert called == []
    assert history.list_run_admissions("s") == []
    assert not (tmp_path / "runs.db").exists()


def test_materialization_failure_does_not_start_the_agent(tmp_path, monkeypatch):
    called = []
    bridge, history = _bridge(tmp_path, monkeypatch, lambda *_args, **_kwargs: called.append(True))

    def fail(_run_id):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(history, "start_run_admission", fail)
    reply = AgentBridge.agent_reply(
        bridge, "input", {"session_id": "s", "request_id": "r1"}
    )
    assert reply.type == ReplyType.ERROR
    assert called == []
    assert history.load_messages("s") == []
    assert history.list_run_admissions("s")[0]["status"] == "failed"


def test_scheduled_run_uses_source_session_execution_settings():
    calls = []

    class AgentStub:
        tools = []
        model = SimpleNamespace()
        _last_run_new_messages = []

        def run_stream(self, **kwargs):
            calls.append(("run", kwargs["user_message"]))
            return "done"

    bridge = AgentBridge.__new__(AgentBridge)
    bridge.agent_registry = SimpleNamespace(default_agent_id="default")
    bridge.route_context = lambda _context: "default"
    bridge.get_agent = lambda session_id=None, agent_id=None: AgentStub()
    bridge._apply_session_project = lambda _agent, session_id, _agent_id: calls.append(("project", session_id))
    bridge.apply_session_prefs = lambda _agent, session_id, _agent_id: calls.append(("prefs", session_id))
    bridge._trim_in_memory_to_turns = lambda *_args: None
    bridge._pre_persist_user_message = lambda *_args: False
    bridge._schedule_mcp_hot_reload = lambda *_args: None

    context = Context(kwargs={
        "session_id": "scheduler_task-1", "request_id": "request-1",
        "execution_session_id": "source-conversation",
        "is_scheduled_task": True, "channel_type": "web",
    })
    reply = bridge._agent_reply_impl("scheduled work", context)

    assert reply.type == ReplyType.TEXT
    assert calls[:2] == [
        ("project", "source-conversation"),
        ("prefs", "source-conversation"),
    ]
    assert calls[-1] == ("run", "scheduled work")


def test_fifo_reservation_prevents_three_admissions_overtaking_slow_record(tmp_path, monkeypatch):
    paused = threading.Event()
    release = threading.Event()
    calls = []
    history = None
    def run(query, context, *_args, **_kwargs):
        calls.append(query)
        history.append_messages('s', [_assistant(query+' reply')])
        return Reply(ReplyType.TEXT, query)
    bridge, history = _bridge(tmp_path, monkeypatch, run)
    real = RunRecord
    class SlowRecord(real):
        def __init__(self):
            super().__init__(tmp_path/'runs.db')
        def create(self, *args, **kwargs):
            super().create(*args, **kwargs)
            if kwargs.get('request_id')=='first':
                paused.set()
                assert release.wait(3)
    monkeypatch.setattr('agent.runtime.run_record.RunRecord', SlowRecord)
    threads=[]
    def invoke(query):
        AgentBridge.agent_reply(bridge,query,{'session_id':'s','request_id':query})
    first=threading.Thread(target=invoke,args=('first',))
    first.start()
    threads.append(first)
    assert paused.wait(3)
    for query in ('second','third'):
        thread=threading.Thread(target=invoke,args=(query,))
        thread.start()
        threads.append(thread)
        deadline=time.monotonic()+3
        while not any(row['request_id']==query for row in history.list_run_admissions('s')):
            assert time.monotonic()<deadline
            time.sleep(.01)
    assert calls==[]
    assert history.list_sessions()['sessions'][0]['session_id']=='s'
    release.set()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert calls==['first','second','third']
    assert [m['content'][0]['text'] for m in history.load_messages('s')]==['first','first reply','second','second reply','third','third reply']
