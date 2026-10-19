from __future__ import annotations

import ast
import importlib
import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.services import elearning_gateway

WORKSPACE_ROOT = Path("stella-plugins-workspace/plugins/elearning")
SIBLING_ROOT = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "elearning"
BASE = "https://elearning.fudan.edu.cn"
PASSWORD = "campus-secret-77"


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    from core.plugins.authz import PluginAuthorizationStore
    monkeypatch.setattr(elearning_gateway, "DEFAULT_AUTHZ", PluginAuthorizationStore())
    monkeypatch.setenv("STELLA_ELEARNING_PLUGIN", "1")
    monkeypatch.setenv("STELLA_ELEARNING_PLUGIN_ROOT", str(WORKSPACE_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    saved = set(elearning_gateway._PURPOSES)
    yield
    elearning_gateway._PURPOSES.clear()
    elearning_gateway._PURPOSES.update(saved)
    elearning_gateway.shutdown_elearning_session()


def _plugin_roots():
    roots = [WORKSPACE_ROOT]
    if SIBLING_ROOT.is_dir():
        roots.append(SIBLING_ROOT)
    return roots


def _load_plugin_main():
    spec = importlib.util.spec_from_file_location(
        "stella_elearning_entry_for_test", WORKSPACE_ROOT / "backend" / "main.py")
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


def _load_vendored(name="stella_elearning_domain_under_test"):
    root = (WORKSPACE_ROOT / "backend" / "domain").resolve()
    spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    return importlib.import_module(name + ".service")


@pytest.mark.parametrize("root", _plugin_roots())
def test_plugin_package_has_no_host_imports(root):
    offenders = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            offenders += [f"{path}: {n}" for n in names if n.split(".")[0] in {"agent", "common", "channel", "application", "core"}]
    assert offenders == []


def test_plugin_never_prints_to_the_rpc_stdout():
    for path in WORKSPACE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "print"], path


def test_descriptors_match_gateway_table_and_purposes_cover_every_method():
    from application.api import _METHODS

    descriptor = _load_plugin_main().SERVICE_DESCRIPTORS[0]
    assert descriptor["contract"] == "stella.elearning@1"
    methods = {m["name"]: m for m in descriptor["methods"]}
    table = elearning_gateway.ELEARNING_METHOD_PARAMS
    assert set(methods) == set(table)
    assert set(_METHODS["elearning"]) == set(table) - {"drain_audit_events"}
    assert set(elearning_gateway.METHOD_PURPOSE) == set(table)
    assert set(elearning_gateway.METHOD_PURPOSE.values()) <= set(elearning_gateway.ALL_PURPOSES)
    for name, method in methods.items():
        assert tuple(method["inputSchema"]["properties"]) == table[name]


def _call(method, params, data_dir, **kw):
    return elearning_gateway.invoke_elearning(method, params, data_dir=data_dir, **kw)


def _settings(**changes):
    return {"enabled": True, "username": "student", "password": PASSWORD, "courses": ["42"], **changes}


def test_settings_roundtrip_masks_secret_and_stays_in_plugin_dir(tmp_path):
    data = tmp_path / "elearning"
    saved = _call("save_settings", {"payload": _settings()}, data)
    assert saved["status"] == "succeeded"
    public = saved["value"]
    assert public["configured"] and public["password_masked"] == "********" and public["password_set"]
    got = _call("get_settings", {}, data)["value"]
    assert got == public and PASSWORD not in json.dumps(got) and PASSWORD not in json.dumps(saved)
    assert (data / "elearning.json").stat().st_mode & 0o777 == 0o600
    kept = _call("save_settings", {"payload": {"password": "********", "courses": ["43"]}}, data)
    assert kept["value"]["courses"] == ["43"]
    other = _call("save_settings", {"payload": {"username": "other", "password": "********"}}, data)
    assert other["status"] == "failed" and other["error"]["code"] == "invalid_argument"
    grant_via_settings = _call("save_settings", {"payload": {"file_sync_enabled": True}}, data)
    assert grant_via_settings["status"] == "failed"
    bad = _call("save_settings", {"payload": {"base_url": "http://elearning.example.com"}}, data)
    assert bad["status"] == "failed"
    gone = _call("delete_settings", {}, data)["value"]
    assert gone["username"] == "" and gone["enabled"] is False


def test_file_sync_grant_is_separate_and_audited_through_drain(tmp_path):
    data, root = tmp_path / "elearning", tmp_path / "saved"
    root.mkdir()
    _call("save_settings", {"payload": _settings()}, data)
    granted = _call("save_file_sync_settings", {"enabled": True, "root": str(root)}, data)
    assert granted["value"]["file_sync_enabled"] and granted["value"]["file_sync_root"] == str(root.resolve())
    events = _call("drain_audit_events", {}, data)["value"]
    assert [(e["tool"], e["operation"], e["decision"]) for e in events] == [("elearning", "configure", "policy_change")]
    assert _call("drain_audit_events", {}, data)["value"] == []
    missing = _call("save_file_sync_settings", {"enabled": True, "root": str(tmp_path / "nope")}, data)
    assert missing["status"] == "failed"


def test_missing_credentials_and_unknown_inputs_fail_without_network(tmp_path):
    data = tmp_path / "elearning"
    for method in ("list_courses", "fetch", "list_files", "sync_files"):
        result = _call(method, {}, data)
        assert result["status"] == "failed" and result["error"]["code"] == "invalid_argument", method
    assert _call("fetch_source", {}, data)["error"]["message"] == "eLearning 来源未启用"
    assert _call("fetch", {"bogus": 1}, data)["error"]["code"] == "invalid_argument"
    assert _call("test_connection", {"payload": {"username": ""}}, data)["status"] == "failed"
    _call("save_settings", {"payload": _settings()}, data)
    assert _call("fetch", {"limit": 0}, data)["error"]["code"] == "invalid_argument"
    assert _call("fetch", {"since": "2026-09-09T00:00:00Z", "until": "2026-09-08T00:00:00Z"}, data)["status"] == "failed"
    assert _call("sync_files", {}, data)["error"]["message"].startswith("请先在 Agent 设置中开启课件保存")


def test_cursors_are_account_scoped_and_only_advance_on_set(tmp_path):
    data = tmp_path / "elearning"
    _call("save_settings", {"payload": _settings()}, data)
    assert _call("get_cursors", {}, data)["value"] == {}
    done = _call("set_cursors", {"cursors": {"elearning_state": "{}"}}, data)
    assert done["value"] == {"elearning_state": "{}"}
    assert _call("set_cursors", {"cursors": {"k": 1}}, data)["error"]["code"] == "invalid_argument"
    _call("save_settings", {"payload": {"username": "other", "password": "x"}}, data)
    assert _call("get_cursors", {}, data)["value"] == {}


def test_discover_read_background_and_sync_purposes_are_separately_authorized(tmp_path):
    # No credentials are saved, so an authorized call fails fast before any network or browser login.
    data = tmp_path / "elearning"
    elearning_gateway.set_elearning_purposes({"interactive", "read"})
    assert _call("get_settings", {}, data)["status"] == "succeeded"
    assert _call("fetch", {}, data)["error"]["code"] == "invalid_argument"  # authorized; rejected by the domain
    for method, params in (("list_courses", {}), ("test_connection", {"payload": {}}),
                           ("fetch_source", {}), ("get_cursors", {}), ("sync_files", {})):
        with pytest.raises(PermissionError, match="purpose not authorized"):
            _call(method, params, data)
    elearning_gateway.set_elearning_purposes({"interactive", "background"})
    assert _call("get_cursors", {}, data)["status"] == "succeeded"
    with pytest.raises(PermissionError):
        _call("fetch", {}, data)
    with pytest.raises(PermissionError):
        _call("list_files", {}, data)
    # An explicit purpose cannot widen what the grant allows.
    with pytest.raises(PermissionError):
        _call("get_settings", {}, data, purpose="discover")


def test_legacy_briefing_directory_is_adopted_without_overwriting(tmp_path):
    legacy, data = tmp_path / "briefing", tmp_path / "elearning"
    (legacy / "elearning-sessions").mkdir(parents=True)
    (legacy / "elearning.json").write_text(json.dumps(_settings()), encoding="utf-8")
    (legacy / "elearning-sessions" / "canvas-x.json").write_text("{}", encoding="utf-8")
    got = _call("get_settings", {}, data, legacy_dir=legacy)["value"]
    assert got["username"] == "student" and got["password_set"] is True
    assert (data / "elearning-sessions" / "canvas-x.json").is_file()
    _call("save_settings", {"payload": {"courses": ["99"]}}, data, legacy_dir=legacy)
    again = _call("get_settings", {}, data, legacy_dir=legacy)["value"]
    assert again["courses"] == ["99"]  # plugin copy wins; legacy file untouched
    assert json.loads((legacy / "elearning.json").read_text())["courses"] == ["42"]


def test_migration_entry_applies_and_verifies(tmp_path):
    path = (WORKSPACE_ROOT / "backend" / "migrate.py").resolve()
    spec = importlib.util.spec_from_file_location("stella_elearning_migrate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]
    handle = {"dataDir": str(tmp_path / "elearning")}
    assert module.verify("m1", handle)["verified"] is False
    assert module.apply("m1", handle)["applied"] is True
    verified = module.verify("m1", handle)
    assert verified["verified"] is True and verified["missingTables"] == []


def test_commit_package_and_invoke_service(tmp_path):
    from core.plugins.host import PluginSession
    from core.plugins.package_ops import PackageStage, PackageStore
    from core.plugins.runtime_hub import DEFAULT_REGISTRY

    store = PackageStore(tmp_path / "pkg")
    op = store.stage(WORKSPACE_ROOT)
    op = store.prepare(store.inspect(op.operation_id).operation_id)
    op = store.commit(op.operation_id)
    assert op.stage == PackageStage.COMMITTED
    session = PluginSession(Path(store.current_package("stella.elearning")["path"]),
                            source_label="local-cache", registry=DEFAULT_REGISTRY)
    try:
        assert session.start()["initialize"]["pluginId"] == "stella.elearning"
        got = session.invoke("get_settings", {"_dataHandle": {"dataDir": str(tmp_path / "elearning")}})
        assert got["status"] == "succeeded" and got["value"]["username"] == ""
    finally:
        session.dispose()


def test_official_catalog_digest_matches_package():
    from core.plugins.distribution import verify_package_digest

    catalog = SIBLING_ROOT.parents[1] / "catalog" / "official.json"
    if not catalog.is_file():
        pytest.skip("Stella-Plugins checkout not present")
    entry = next(e for e in json.loads(catalog.read_text())["plugins"] if e["pluginId"] == "stella.elearning")
    assert verify_package_digest(SIBLING_ROOT, entry["sha256"])


# ---- facade / Application port --------------------------------------------

def _patch_paths(monkeypatch, tmp_path):
    from core.services import elearning_facade

    monkeypatch.setattr(elearning_facade, "_paths", lambda: (tmp_path / "elearning", tmp_path / "briefing"))


def test_application_port_and_facade_records_audit_on_host(tmp_path, monkeypatch):
    from application.api import Application
    from common.runtime_identity import RuntimeIdentity, use_identity

    _patch_paths(monkeypatch, tmp_path)
    recorded = []
    monkeypatch.setattr("agent.permission.audit.record", lambda **event: recorded.append(event))
    root = tmp_path / "saved"
    root.mkdir()
    with use_identity(RuntimeIdentity(agent_id="a", user_id="u")):
        port = Application.port("elearning")
        port.save_settings(_settings())
        assert port.get_settings()["configured"] is True
        port.save_file_sync_settings(True, str(root))
        assert [(e["tool"], e["decision"]) for e in recorded] == [("elearning", "policy_change")]
        with pytest.raises(ValueError):
            port.save_settings({"file_sync_root": "x"})
        monkeypatch.delenv("STELLA_ELEARNING_PLUGIN")
        with pytest.raises(RuntimeError, match="stella.elearning"):
            Application.port("elearning")


def test_facade_legacy_names_and_source_registration(tmp_path, monkeypatch):
    from core.services import elearning_facade

    _patch_paths(monkeypatch, tmp_path)
    facade = elearning_facade.ElearningPluginFacade()
    assert elearning_facade.elearning_sources() == []
    facade.save_settings(_settings())
    assert facade.public_settings()["username"] == "student"
    [source] = elearning_facade.elearning_sources()
    assert source.name == "elearning" and source.account_id == facade.get_settings()["account_id"]
    assert not hasattr(source, "config")
    facade.save_settings({"enabled": False})
    assert elearning_facade.elearning_sources() == []


def test_source_adapter_maps_plugin_items():
    from core.services.elearning_facade import ElearningPluginSource

    seen = {}

    class Stub:
        def fetch_source(self, cursors=None, **window):
            seen.update(cursors=cursors, **window)
            return {"items": [{"source": "elearning", "source_id": "42:file:1", "account_id": "canvas-x"}],
                    "cursors": {"elearning_state": "{}"}, "errors": ["partial"]}

    result = ElearningPluginSource(account_id="canvas-x", facade=Stub()).fetch(
        {"elearning_state": "s", "since": "S", "until": "U"})
    assert seen == {"cursors": {"elearning_state": "s"}, "since": "S", "until": "U"}
    assert result.items[0].source_id == "42:file:1" and result.errors == ["partial"]


# ---- vendored domain with a fake Canvas (in-process) -----------------------

class FakeCanvas:
    base = BASE

    def __init__(self):
        self.rows = {
            "courses": [{"id": 42, "name": "课程"}],
            "discussion_topics": [{"id": 1, "title": "公告", "message": "<p>上课通知</p>",
                                   "posted_at": "2026-09-08T23:00:00Z"}],
            "assignments": [{"id": 2, "name": "作业", "description": "<p>完整作业说明</p>",
                             "updated_at": "2026-09-08T23:00:00Z", "due_at": "2026-09-10T12:00:00Z",
                             "points_possible": 100,
                             "submission": {"workflow_state": "graded", "graded_at": "2026-09-08T23:00:00Z", "score": 0}}],
            "quizzes": [{"id": 3, "title": "测试", "description": "测试要求", "updated_at": "2026-09-08T23:00:00Z"}],
            "files": [{"id": 4, "filename": "讲义.pdf", "display_name": "讲义.pdf", "size": 3,
                       "updated_at": "2026-09-08T23:00:00Z", "url": BASE + "/files/4/download"},
                      {"id": 5, "filename": "作业.pdf", "display_name": "作业.pdf", "size": 3,
                       "updated_at": "2026-09-08T23:00:00Z", "url": BASE + "/files/5/download"}],
            "enrollments": [{"id": 5, "grades": {"current_score": 0}}],
        }
        self.open = Mock(side_effect=lambda *args, **kwargs: io.BytesIO(b"pdf"))

    def get(self, path, params=None):
        return {"id": 99}, None

    def list(self, path, params=None):
        rows = self.rows[path.rsplit("/", 1)[-1]]
        if isinstance(rows, Exception):
            raise rows
        return rows


def _service(tmp_path, canvas=None, **kw):
    module = _load_vendored()
    canvas = canvas or FakeCanvas()
    def clock():
        return datetime(2026, 9, 9, 8, tzinfo=timezone.utc)
    return module.ElearningService(tmp_path / "elearning", client_factory=lambda cfg: canvas, clock=clock, **kw), canvas


def test_domain_courses_connection_and_options(tmp_path):
    service, _ = _service(tmp_path)
    service.save_settings(_settings())
    assert service.list_courses() == [{"id": "42", "name": "课程"}]
    options = service.test_connection({"password": "********"})
    assert options == [{"id": "42", "name": "课程"}]
    assert service.get_settings()["course_options"] == options


def test_domain_fetch_source_proposes_state_and_set_cursors_commits(tmp_path):
    service, _ = _service(tmp_path)
    service.save_settings(_settings())
    window = {"since": "2026-09-08T12:00:00Z", "until": "2026-09-09T00:00:00Z"}
    result = service.fetch_source(**window)
    assert result["errors"] == [] and result["source"] == "elearning"
    assert {i["payload"]["resource_type"] for i in result["items"]} == {
        "announcement", "assignment", "quiz", "grade", "course_grade", "file"}
    assert PASSWORD not in json.dumps(result)
    assert service.get_cursors() == {}  # proposed only
    service.set_cursors(result["cursors"])
    again = service.fetch_source(since="2026-09-09T00:00:00Z", until="2026-09-10T00:00:00Z")
    assert again["items"] == []
    service.save_settings({"enabled": False})
    with pytest.raises(ValueError, match="未启用"):
        service.fetch_source()


def test_domain_partial_read_does_not_propose_cursor(tmp_path):
    service, canvas = _service(tmp_path)
    service.save_settings(_settings())
    errors = importlib.import_module("stella_elearning_domain_under_test.errors")
    canvas.rows["quizzes"] = errors.SyncError("网站返回 HTTP 500。")
    result = service.fetch_source(since="2026-09-08T12:00:00Z", until="2026-09-09T00:00:00Z")
    assert result["cursors"] == {} and result["errors"] and "quizzes" in result["errors"][0]


def test_domain_fetch_pages_and_filters_window(tmp_path):
    service, _ = _service(tmp_path)
    service.save_settings(_settings())
    page = service.fetch(since="2026-09-08T12:00:00Z", until="2026-09-09T00:00:00Z", limit=2)
    assert page["total"] == 7 and len(page["source_items"]) == 2 and page["next_offset"] == 2
    assert page["status"] == "completed"
    outside = service.fetch(since="2026-09-10T00:00:00Z", until="2026-09-11T00:00:00Z")
    # Dated items fall out of the window; only items first seen without a usable timestamp are observed "now".
    assert outside["total"] < page["total"]
    assert all("2026-09-10" < i["occurred_at"] <= "2026-09-11T00:00:01Z" for i in outside["source_items"])
    with pytest.raises(ValueError, match="course_ids"):
        service.fetch(course_ids=[""])


def test_domain_list_and_sync_files_only_to_granted_folder(tmp_path):
    service, canvas = _service(tmp_path)
    root = tmp_path / "selected"
    root.mkdir()
    service.save_settings(_settings(enabled=False))
    service.save_file_sync_settings(True, str(root))
    listed = service.list_files(file_extensions=["pdf"])
    assert listed["total"] == 2 and listed["files"][0]["filename"] == "讲义.pdf"
    assert service.list_files(file_extensions=["docx"])["total"] == 0
    result = service.sync_files(file_ids=["5"])
    assert result == {"status": "completed", "total": 1, "processed": 1, "next_offset": None,
                      "save_root": str(root.resolve()), "errors": []}
    assert (root.resolve() / "课程--42" / "作业--5.pdf").read_bytes() == b"pdf"
    assert not (root.resolve() / "课程--42" / "讲义--4.pdf").exists()
    with pytest.raises(ValueError, match="已授权"):
        service.sync_files(course_ids=["unselected"])
    courseware = service.sync_files(file_ids=["4"], layout="courseware")
    assert courseware["errors"] == [] and (root.resolve() / "课程" / "课件" / "讲义.pdf").is_file()
    assert "download" in {e["operation"] for e in service.drain_audit_events()}
    service.save_file_sync_settings(False, "")
    with pytest.raises(ValueError, match="Agent 设置中开启课件保存"):
        service.sync_files()
    # Revoking the grant mid-way stops downloads rather than writing to the old folder.
    service.save_file_sync_settings(True, str(root))
    service.save_settings({"courses": ["43"]})
    assert service.get_settings()["file_sync_enabled"] is False
