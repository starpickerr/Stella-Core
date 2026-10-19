from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.services import briefing_gateway

WORKSPACE_ROOT = Path("stella-plugins-workspace/plugins/briefing")
SIBLING_ROOT = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "briefing"

NOW = "2026-09-09T06:00:00Z"


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    monkeypatch.setenv("STELLA_BRIEFING_PLUGIN", "1")
    monkeypatch.setenv("STELLA_BRIEFING_PLUGIN_ROOT", str(WORKSPACE_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    monkeypatch.setenv("STELLA_BRIEFING_HOST_ADAPTERS", "0")
    yield
    briefing_gateway.shutdown_briefing_session()


def _plugin_roots():
    roots = [WORKSPACE_ROOT]
    if SIBLING_ROOT.is_dir():
        roots.append(SIBLING_ROOT)
    return roots


def _call(db, method, **params):
    return briefing_gateway.invoke_briefing(method, params, db_path=db)


def _ok(db, method, **params):
    result = _call(db, method, **params)
    assert result["status"] == "succeeded", result
    return result["value"]


def _fetched(source_id="m1", title="作业提醒", occurred_at=NOW, **extra):
    return {"source": "email", "account_id": "default", "source_id": source_id, "title": title,
            "sender": "Ada", "snippet": "请提交", "occurred_at": occurred_at, "sender_email": "ada@x.edu",
            **extra}


def _complete_with_action_item(db):
    """Complete a briefing whose card has a classified mail snapshot (so actions are prepared)."""
    src = _ok(db, "upsert_source_item", payload=_fetched())["item"]
    _ok(db, "start_briefing", briefing_date="2026-09-09")
    return _ok(db, "complete_briefing", briefing_id="brf-2026-09-09", payload={
        "status": "completed", "run_at": NOW,
        "items": [{"source_item_id": src["id"], "section": "action", "title": "作业",
                   "payload": {"information_type": "assignment"}}],
        "mail": [{"id": src["id"], "source": "email", "account_id": "default", "source_id": "m1",
                  "thread_id": "", "category": "selected", "title": "作业", "occurred_at": NOW,
                  "metadata": {"information_type": "assignment"},
                  "decision": {"category": "needs_action", "section": "action"}}]})


@pytest.mark.parametrize("root", _plugin_roots())
def test_plugin_package_has_no_host_agent_imports_or_secrets(root):
    offenders = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in {"agent", "common", "channel", "application", "core", "models"}:
                    offenders.append(f"{path}: {name}")
    assert offenders == []
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))
    assert "imaplib" not in text and "keyring" not in text.lower()


def _load_entry():
    spec = importlib.util.spec_from_file_location(
        "stella_briefing_entry_for_test", WORKSPACE_ROOT / "backend" / "main.py")
    module = importlib.util.module_from_spec(spec)
    backend = str((WORKSPACE_ROOT / "backend").resolve())
    sys.path.insert(0, backend)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(backend)
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]
    return module


def test_descriptors_cover_application_briefing_methods_and_gateway_table():
    from application.api import _METHODS
    from core.services.briefing_facade import APPLICATION_METHODS

    module = _load_entry()
    descriptor = module.SERVICE_DESCRIPTORS[0]
    assert descriptor["contract"] == "stella.briefing@1"
    methods = {m["name"]: m for m in descriptor["methods"]}
    assert len(_METHODS["briefing"]) == 25
    assert set(_METHODS["briefing"]) == set(APPLICATION_METHODS) == set(module.BRIEFING_APPLICATION_METHODS)
    assert set(_METHODS["briefing"]) <= set(methods)
    assert set(methods) == set(briefing_gateway.BRIEFING_METHOD_PARAMS)
    for name, method in methods.items():
        assert tuple(method["inputSchema"]["properties"]) == briefing_gateway.BRIEFING_METHOD_PARAMS[name]
        expected = "briefing.write" if name in briefing_gateway.BRIEFING_WRITE_METHODS else "briefing.read"
        assert method["permissions"] == [expected]


def test_list_get_start_and_missing(tmp_path):
    db = tmp_path / "briefing.db"
    assert _ok(db, "list_briefings") == []
    started = _ok(db, "start_briefing", briefing_date="2026-09-09", title="今日")
    assert started["id"] == "brf-2026-09-09" and started["status"] == "running"
    assert _ok(db, "get_briefing", briefing_id="brf-2026-09-09")["briefing"]["title"] == "今日"
    assert _ok(db, "get_briefing", briefing_id="brf-none") is None
    assert _ok(db, "briefing_for_date", briefing_date="2026-09-09")["id"] == "brf-2026-09-09"
    assert [b["id"] for b in _ok(db, "list_briefings", status="running")] == ["brf-2026-09-09"]
    bad = _call(db, "list_briefings", status="bogus")
    assert bad["status"] == "failed" and bad["error"]["code"] == "invalid_argument"
    missing = _call(db, "get_revision", briefing_id="brf-none", number=1)
    assert missing["status"] == "failed" and missing["error"]["code"] == "not_found"


def test_rules_roundtrip(tmp_path):
    db = tmp_path / "briefing.db"
    rule = _ok(db, "create_rule", payload={"text": "排除广告", "source": "email"})
    assert rule["text"] == "排除广告" and rule["enabled"] is True
    assert [r["id"] for r in _ok(db, "list_rules", enabled_only=True, source="email")] == [rule["id"]]
    updated = _ok(db, "update_rule", rule_id=rule["id"], payload={"enabled": False})
    assert updated["enabled"] is False
    assert _ok(db, "list_rules", enabled_only=True) == []
    assert _ok(db, "get_rule", rule_id=rule["id"])["id"] == rule["id"]
    assert _ok(db, "delete_rule", rule_id=rule["id"]) == {"deleted": True, "id": rule["id"]}
    assert _call(db, "delete_rule", rule_id=rule["id"])["error"]["code"] == "not_found"
    assert _call(db, "create_rule", payload={"text": " "})["error"]["code"] == "invalid_argument"


def test_cursors_and_source_catalog(tmp_path):
    db = tmp_path / "briefing.db"
    assert _ok(db, "get_cursor", source="email", account_id="default", cursor_key="imap_uid") is None
    saved = _ok(db, "set_cursor", source="email", cursor_key="imap_uid", cursor_value="42", account_id="work")
    assert saved["cursor_value"] == "42" and saved["account_id"] == "work"
    got = _ok(db, "get_cursor", source="email", account_id="work", cursor_key="imap_uid")
    assert got["cursor_value"] == "42"
    pair = _ok(db, "upsert_source_item", payload=_fetched())
    assert pair["item"]["source_id"] == "m1" and pair["email"]["sender_email"] == "ada@x.edu"
    built = _ok(db, "build_source_item", payload=_fetched(source_id="m2"))
    assert built["item"]["source_id"] == "m2"
    assert _call(db, "upsert_source_item", payload={"source": "email"})["error"]["code"] == "invalid_argument"


def test_complete_briefing_items_revisions_status_and_decisions(tmp_path):
    db = tmp_path / "briefing.db"
    _ok(db, "start_briefing", briefing_date="2026-09-09")
    done = _ok(db, "complete_briefing", briefing_id="brf-2026-09-09", payload={
        "status": "completed", "run_at": NOW, "title": "简报", "body": "正文",
        "items": [{"source": "email", "source_id": "m1", "occurred_at": NOW, "section": "action",
                   "title": "作业", "sender": "Ada", "snippet": "交作业", "score": 80}],
        "cursor_updates": [["email", "default", "imap_uid", "9"]],
    })
    assert done["briefing"]["status"] == "completed" and len(done["items"]) == 1
    item_id = done["items"][0]["id"]
    assert [r["number"] for r in _ok(db, "list_revisions", briefing_id="brf-2026-09-09")] == [1]
    revision = _ok(db, "get_revision", briefing_id="brf-2026-09-09", number=1)
    assert revision["items"][0]["id"] == item_id
    assert _ok(db, "get_cursor", source="email", account_id="default", cursor_key="imap_uid")["cursor_value"] == "9"
    assert _ok(db, "update_item_status", item_id=item_id, status="done")["status"] == "done"
    assert _call(db, "update_item_status", item_id="nope", status="done")["error"]["code"] == "not_found"
    assert _call(db, "update_item_status", item_id=item_id, status="x")["error"]["code"] == "invalid_argument"
    overview = _ok(db, "get_overview")
    assert [row["id"] for row in overview["items"]] == [item_id]


def test_action_rules_preferences_and_adapter_bound_operations(tmp_path):
    db = tmp_path / "briefing.db"
    rule = _ok(db, "create_action_rule", payload={
        "source": "email", "account_id": "default", "information_type": "assignment",
        "kind": "todo", "mode": "suggest"})
    assert [r["id"] for r in _ok(db, "list_action_rules")] == [rule["id"]]
    assert _ok(db, "delete_action_rule", rule_id=rule["id"])["deleted"] is True
    assert _ok(db, "get_preferences")["summary_detail"] == "brief"
    assert _ok(db, "update_preferences", payload={"summary_detail": "full"})["summary_detail"] == "full"
    assert _call(db, "update_preferences", payload={"bogus": 1})["error"]["code"] == "invalid_argument"
    unsupported = _call(db, "get_action_targets", kind="todo", query="")
    assert unsupported["status"] == "failed" and unsupported["error"]["code"] == "permission_denied"

    done = _complete_with_action_item(db)
    item_id = done["items"][0]["id"]
    assert done["actions"][item_id]["todo"]["state"] == "pending"
    ignored = _ok(db, "update_action", item_id=item_id, payload={"operation": "ignore", "kind": "todo"})
    assert ignored["state"] == "ignored"
    create = _call(db, "update_action", item_id=item_id, payload={"operation": "create", "kind": "todo"})
    assert create['status'] == 'succeeded'
    assert create['value']['state'] == 'failed' and not create['value'].get('target_id')
    assert 'not installed' in create['value']['error']
    outbox = _ok(db, "dispatch_outbox", limit=5)
    assert outbox["pending"] == 0 and outbox["projected"] == 2


def test_source_selection_uses_core_source_directory(tmp_path):
    db = tmp_path / "briefing.db"
    from core.services.sources_public import SourceDescriptor, SourceDirectory

    directory = SourceDirectory()
    directory.upsert(SourceDescriptor("email:work", "stella.email", "email", "工作邮箱"))
    directory.upsert(SourceDescriptor("elearning:school", "stella.elearning", "elearning", "学校"))
    directory.upsert(SourceDescriptor("email:old", "stella.email", "email", "旧邮箱", status="disabled"))
    rows = briefing_gateway.invoke_briefing(
        "list_sources", {}, db_path=db, source_directory=directory.list_for_user())["value"]
    assert [r["id"] for r in rows] == ["email:work", "elearning:school"]
    chosen = briefing_gateway.invoke_briefing(
        "select_sources", {"selectors": ["email"]}, db_path=db,
        source_directory=directory.list_for_user())["value"]
    assert [r["id"] for r in chosen] == ["email:work"]
    bad = briefing_gateway.invoke_briefing(
        "select_sources", {"selectors": ["nope"]}, db_path=db, source_directory=directory.list_for_user())
    assert bad["status"] == "failed" and bad["error"]["code"] == "invalid_argument"
    everything = briefing_gateway.invoke_briefing(
        "select_sources", {"selectors": ["all"]}, db_path=db, source_directory=directory.list_for_user())
    assert len(everything["value"]) == 2


def test_run_pipeline_accepts_prefetched_items_and_advances_cursors_only_on_success(tmp_path):
    db = tmp_path / "briefing.db"
    sources = [
        {"source": "email", "account_id": "default", "name": "邮箱", "items": [_fetched()],
         "cursors": {"imap_uid": "7"}},
        {"source": "elearning", "account_id": "school", "name": "学校", "items": [],
         "cursors": {"elearning_state": "s1"}, "errors": ["课程读取失败"]},
    ]
    detail = _ok(db, "run_pipeline", briefing_date="2026-09-09", operation="upsert", trigger="manual",
                 sources=sources)
    assert detail["briefing"]["status"] == "partial"
    assert detail["briefing"]["fetched_count"] == 1 and len(detail["items"]) == 1
    assert "课程读取失败" in detail["briefing"]["error_message"]
    assert set(detail["briefing"]["source_windows"]) == {"email:default"}
    assert _ok(db, "get_cursor", source="email", account_id="default", cursor_key="imap_uid")["cursor_value"] == "7"
    assert _ok(db, "get_cursor", source="elearning", account_id="school", cursor_key="elearning_state") is None
    again = _ok(db, "run_pipeline", briefing_date="2026-09-09", operation="create", sources=sources)
    assert again["briefing"]["id"] == detail["briefing"]["id"]
    assert _call(db, "run_pipeline", briefing_date="2026-09-09", operation="update", sources=[])["error"][
        "code"] == "invalid_argument"
    stub = _call(db, "run_pipeline", briefing_date="2026-09-10", operation="update", sources=sources)
    assert stub["error"]["code"] == "invalid_argument"


def test_run_pipeline_with_host_draft_and_all_sources_failed(tmp_path):
    db = tmp_path / "briefing.db"
    draft = {"title": "自定义", "body": "AI 正文", "rule_text": "r", "items": [
        {"source_item_id": None, "source": "email", "source_id": "m1", "occurred_at": NOW, "section": "action",
         "title": "作业", "snippet": "s", "score": 90}], "mail": []}
    out = _ok(db, "run_pipeline", briefing_date="2026-09-09", sources=[
        {"source": "email", "items": [_fetched()]}], draft=draft)
    assert out["briefing"]["title"] == "自定义" and out["briefing"]["body"] == "AI 正文"
    assert out["items"][0]["section"] == "action"
    failed = _ok(db, "run_pipeline", briefing_date="2026-09-11", sources=[
        {"source": "email", "items": [], "errors": ["boom"]}])
    assert failed["briefing"]["status"] == "failed" and failed["briefing"]["error_message"] == "email: boom"


def _patch_paths(monkeypatch, tmp_path):
    from core.services import briefing_facade

    monkeypatch.setattr(briefing_facade, "_db_path", lambda: tmp_path / "briefing.db")


def test_application_port_routes_briefing_via_plugin_with_core_models(tmp_path, monkeypatch):
    from agent.briefing.models import Briefing, BriefingItem, FilterRule, SyncCursor
    from application.api import Application
    from common.runtime_identity import RuntimeIdentity, use_identity

    _patch_paths(monkeypatch, tmp_path)
    with use_identity(RuntimeIdentity(agent_id="test-agent", user_id="test-user")):
        port = Application.port("briefing")
        started = port.start_briefing("2026-09-09", "今日")
        assert isinstance(started, Briefing) and started.status == "running"
        detail = port.complete_briefing(started.id, {
            "status": "completed", "run_at": NOW, "title": "简报",
            "items": [{"source": "email", "source_id": "m1", "occurred_at": NOW, "title": "作业"}]})
        assert isinstance(detail["briefing"], Briefing) and isinstance(detail["items"][0], BriefingItem)
        assert port.get_briefing(started.id)["briefing"].title == "简报"
        assert port.get_briefing("brf-none") is None
        assert [b.id for b in port.list_briefings(status="completed")] == [started.id]
        assert port.briefing_for_date("2026-09-09").id == started.id
        rule = port.create_rule({"text": "排除广告"})
        assert isinstance(rule, FilterRule)
        assert [r.id for r in port.list_rules()] == [rule.id]
        assert port.update_rule(rule.id, {"enabled": False}).enabled is False
        assert port.delete_rule(rule.id) is None
        with pytest.raises(KeyError):
            port.get_revision("brf-none", 1)
        with pytest.raises(KeyError):
            port.delete_rule("missing")
        with pytest.raises(ValueError):
            port.create_rule({"text": ""})
        cursor = port.set_cursor("email", "imap_uid", "5")
        assert isinstance(cursor, SyncCursor) and port.get_cursor("email", "default", "imap_uid").cursor_value == "5"
        item, email = port.upsert_source_item({"source": "email", "source_id": "m9", "occurred_at": NOW,
                                               "sender_email": "a@b.c"})
        assert item.source_id == "m9" and email.sender_email == "a@b.c"
        assert port.get_preferences()["reminder_frequency"] == "daily"
        assert port.get_overview()["items"][0].source_id == "m1"
        item_id = detail["items"][0].id
        assert port.update_item_status(item_id, "done").status == "done"


def test_failed_peer_action_never_falls_back_to_core_writer(tmp_path, monkeypatch):
    from core.services.briefing_facade import BriefingPluginFacade

    _patch_paths(monkeypatch, tmp_path)
    db = tmp_path / 'briefing.db'
    item_id = _complete_with_action_item(db)['items'][0]['id']
    monkeypatch.setenv('STELLA_BRIEFING_HOST_ADAPTERS', '1')
    import importlib.util
    assert importlib.util.find_spec('agent.briefing.service') is None
    result = BriefingPluginFacade().update_action(item_id, {'operation':'create', 'kind':'todo'})
    assert result['state'] == 'failed' and 'not installed' in result['error']
    assert not hasattr(BriefingPluginFacade, '_host_update_action')


def test_action_target_query_is_owned_by_briefing_worker(tmp_path, monkeypatch):
    from core.services.briefing_facade import BriefingPluginFacade
    from core.services import briefing_gateway
    from application import Application

    seen = []
    monkeypatch.setattr(Application, 'port', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Core peer lookup used')))

    def invoke(method, params, **kwargs):
        seen.append((method, params))
        return {'status':'succeeded','sideEffects':'none','value':[{'title':'写周报'}]}

    monkeypatch.setattr(briefing_gateway, 'invoke_briefing', invoke)
    assert BriefingPluginFacade().get_action_targets('todo', '周报') == [{'title':'写周报'}]
    assert seen == [('get_action_targets', {'kind':'todo', 'query':'周报'})]


def test_core_pipeline_runs_through_plugin_store_proxy(tmp_path, monkeypatch):
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.sources.base import FetchedItem
    from briefing_fakes import StaticSource
    from core.services.briefing_facade import BriefingPluginFacade

    _patch_paths(monkeypatch, tmp_path)

    class Drafter:
        def generate(self, rows, rules, *, briefing_date, window_start, window_end, preserved_decisions=None):
            cards, mail = [], []
            for index, (item, email) in enumerate(rows):
                mail.append({"id": item.id, "source": item.source, "account_id": item.account_id,
                             "source_id": item.source_id, "thread_id": item.thread_id,
                             "category": "selected", "title": item.title, "metadata": {},
                             "occurred_at": item.occurred_at, "decision": {"category": "needs_action"}})
                cards.append({"source_item_id": item.id, "section": "fyi", "score": 60, "sort_order": index,
                              "snippet": item.snippet})
            return {"title": "T", "body": f"{len(rows)} 条", "items": cards, "mail": mail, "rule_text": "r"}

    source = StaticSource([FetchedItem(source="email", source_id="m1", title="作业", snippet="s",
                                       occurred_at=NOW, account_id="default", sender="Ada")],
                          cursors={"imap_uid": "3"})
    facade = BriefingPluginFacade()
    clock = lambda: datetime(2026, 9, 9, 8, tzinfo=timezone.utc)  # noqa: E731
    pipeline = BriefingPipeline(facade, [source], clock=clock, generator=Drafter())
    detail = pipeline.run(briefing_date="2026-09-09", trigger="manual")
    assert detail["briefing"].status == "completed" and detail["briefing"].body == "1 条"
    assert [i.source_id for i in detail["items"]] == ["m1"]
    assert facade.get_cursor("email", "default", "imap_uid").cursor_value == "3"
    assert facade.store.list_revisions("brf-2026-09-09")[0]["number"] == 1
    # The staged candidate was promoted into the plugin-owned catalog.
    rows = facade.store.window_candidates("2026-09-08T00:00:00Z", "2026-09-10T00:00:00Z", [("email", "default")])
    assert [item.source_id for item, _email in rows] == ["m1"]
    # Missing peer authorization keeps the durable event pending in its owner.
    assert _ok(tmp_path / "briefing.db", "dispatch_outbox", limit=5)["pending"] == 1


def test_host_pipeline_persists_only_via_run_pipeline(tmp_path, monkeypatch):
    """Production host fetch/draft must commit through plugin run_pipeline, not host stage/complete."""
    from agent.briefing.pipeline import BriefingPipeline
    from agent.briefing.sources.base import FetchedItem
    from briefing_fakes import StaticSource
    from core.services import briefing_gateway as gw
    from core.services.briefing_facade import BriefingPluginFacade

    _patch_paths(monkeypatch, tmp_path)
    seen: list[str] = []
    real = gw.invoke_briefing

    def track(method, params, **kwargs):
        seen.append(method)
        return real(method, params, **kwargs)

    monkeypatch.setattr(gw, "invoke_briefing", track)

    class Drafter:
        def generate(self, rows, rules, *, briefing_date, window_start, window_end, preserved_decisions=None):
            cards, mail = [], []
            for index, (item, _email) in enumerate(rows):
                mail.append({"id": item.id, "source": item.source, "account_id": item.account_id,
                             "source_id": item.source_id, "thread_id": item.thread_id,
                             "category": "selected", "title": item.title, "metadata": {},
                             "occurred_at": item.occurred_at, "decision": {"id": item.id, "selected": True}})
                cards.append({"source_item_id": item.id, "section": "fyi", "score": 60, "sort_order": index,
                              "snippet": item.snippet, "source": item.source, "account_id": item.account_id,
                              "source_id": item.source_id, "occurred_at": item.occurred_at, "title": item.title})
            return {"title": "HostDraft", "body": "drafted", "items": cards, "mail": mail, "rule_text": "r"}

    source = StaticSource([FetchedItem(source="email", source_id="m9", title="作业", snippet="s",
                                       occurred_at=NOW, account_id="default", sender="Ada")],
                          cursors={"imap_uid": "9"})
    facade = BriefingPluginFacade()
    detail = BriefingPipeline(
        facade, [source], clock=lambda: datetime(2026, 9, 9, 8, tzinfo=timezone.utc), generator=Drafter(),
    ).run(briefing_date="2026-09-09")
    assert detail["briefing"].title == "HostDraft" and detail["briefing"].body == "drafted"
    assert seen.count("run_pipeline") == 1
    # Host may start a running row for progress; snapshot/cursor writes stay in run_pipeline.
    for forbidden in ("complete_briefing", "stage_source_items", "stage_source_errors"):
        assert forbidden not in seen, forbidden


def test_briefing_migration_entry_applies_and_verifies(tmp_path):
    path = (WORKSPACE_ROOT / "backend" / "migrate.py").resolve()
    spec = importlib.util.spec_from_file_location("stella_briefing_migrate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    backend = str(path.parent)
    sys.path.insert(0, backend)
    try:
        spec.loader.exec_module(module)
        handle = {"dbPath": str(tmp_path / "briefing.db")}
        assert module.verify("m1", handle)["verified"] is False
        assert module.apply("m1", handle)["applied"] is True
        verified = module.verify("m1", handle)
        assert verified["verified"] is True and verified["missingTables"] == []
    finally:
        sys.path.remove(backend)
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]


def test_commit_briefing_package_and_invoke_service(tmp_path):
    from core.plugins.host import PluginSession
    from core.plugins.package_ops import PackageStage, PackageStore
    from core.plugins.runtime_hub import DEFAULT_REGISTRY

    store = PackageStore(tmp_path / "pkg")
    op = store.stage(WORKSPACE_ROOT)
    op = store.inspect(op.operation_id)
    op = store.prepare(op.operation_id)
    op = store.commit(op.operation_id)
    assert op.stage == PackageStage.COMMITTED
    current = store.current_package("stella.briefing")
    session = PluginSession(Path(current["path"]), source_label="local-cache", registry=DEFAULT_REGISTRY)
    try:
        assert session.start()["initialize"]["pluginId"] == "stella.briefing"
        listed = session.invoke("list_briefings", {"_dataHandle": {"dbPath": str(tmp_path / "b.db")}})
        assert listed["status"] == "succeeded" and listed["value"] == []
    finally:
        session.dispose()


def test_official_catalog_digest_matches_briefing_package():
    from core.plugins.distribution import verify_package_digest

    catalog = SIBLING_ROOT.parents[1] / "catalog" / "official.json"
    if not catalog.is_file() or not SIBLING_ROOT.is_dir():
        pytest.skip("Stella-Plugins checkout not present")
    entry = next(e for e in json.loads(catalog.read_text())["plugins"] if e["pluginId"] == "stella.briefing")
    assert verify_package_digest(SIBLING_ROOT, entry["sha256"])


def test_missing_briefing_plugin_cannot_create_legacy_database(monkeypatch, tmp_path):
    from application import Application
    monkeypatch.setenv('STELLA_BRIEFING_PLUGIN', '0')
    monkeypatch.setattr('common.state_dir.briefing_db', lambda **_: tmp_path / 'briefing.db')
    with pytest.raises(RuntimeError, match='stella.briefing'):
        Application.port('briefing')
    assert not (tmp_path / 'briefing.db').exists()
