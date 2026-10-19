from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import sys
from email.message import EmailMessage as RfcMessage
from pathlib import Path

import pytest

from core.services import email_gateway

WORKSPACE_ROOT = Path("stella-plugins-workspace/plugins/email")
SIBLING_ROOT = Path(__file__).resolve().parents[2] / "Stella-Plugins" / "plugins" / "email"
SECRET = "imap-app-secret-9f3"
DRAFT = {"host": "127.0.0.1", "user": "ada@example.com", "password": SECRET, "port": 1, "folder": "INBOX"}


@pytest.fixture(autouse=True)
def _cleanup(monkeypatch):
    monkeypatch.setenv("STELLA_EMAIL_PLUGIN", "1")
    monkeypatch.setenv("STELLA_EMAIL_PLUGIN_ROOT", str(WORKSPACE_ROOT.resolve()))
    monkeypatch.setenv("STELLA_REPO_ROOT", str(Path.cwd()))
    for key in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "IMAP_PORT", "IMAP_FOLDER"):
        monkeypatch.delenv(key, raising=False)
    saved = set(email_gateway._PURPOSES)
    yield
    email_gateway._PURPOSES.clear()
    email_gateway._PURPOSES.update(saved)
    email_gateway.shutdown_email_session()


def _plugin_roots():
    roots = [WORKSPACE_ROOT]
    if SIBLING_ROOT.is_dir():
        roots.append(SIBLING_ROOT)
    return roots


def _load_plugin_main():
    spec = importlib.util.spec_from_file_location("stella_email_entry_for_test", WORKSPACE_ROOT / "backend" / "main.py")
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


def _load_vendored(name="stella_email_domain_under_test"):
    root = (WORKSPACE_ROOT / "backend" / "domain").resolve()
    spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    return importlib.import_module(name + ".service"), importlib.import_module(name + ".imap")


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


def test_descriptors_match_gateway_table_and_application_methods():
    from application.api import _METHODS

    descriptor = _load_plugin_main().SERVICE_DESCRIPTORS[0]
    assert descriptor["contract"] == "stella.email@1"
    methods = {m["name"]: m for m in descriptor["methods"]}
    assert set(methods) == set(email_gateway.EMAIL_METHOD_PARAMS) == set(_METHODS["email"])
    for name, method in methods.items():
        assert tuple(method["inputSchema"]["properties"]) == email_gateway.EMAIL_METHOD_PARAMS[name]


def _call(method, params, db, **kw):
    return email_gateway.invoke_email(method, params, db_path=db, **kw)


def test_account_crud_masks_password_and_never_returns_secret(tmp_path):
    db = tmp_path / "email.db"
    saved = _call("save_account", dict(payload=DRAFT), db)
    assert saved["status"] == "succeeded"
    account = saved["value"]
    assert account["configured"] and account["password_masked"] == "********" and account["id"]
    listed = _call("list_accounts", {}, db)
    assert [m["user"] for m in listed["value"]["mailboxes"]] == ["ada@example.com"]
    assert SECRET not in json.dumps(listed) and SECRET not in json.dumps(saved)
    # blank password keeps the saved credential; duplicate mailbox/folder is rejected
    updated = _call("save_account", dict(payload={"id": account["id"], "folder": "Archive", "password": "********"}), db)
    assert updated["value"]["folder"] == "Archive"
    dup = _call("save_account", dict(payload={**DRAFT, "action": "add", "folder": "Archive"}), db)
    assert dup["status"] == "failed" and dup["error"]["code"] == "invalid_argument"
    assert _call("get_account", {"account_id": account["id"]}, db)["value"]["folder"] == "Archive"
    assert _call("get_account", {"account_id": "nope"}, db)["error"]["code"] == "not_found"
    bad = _call("save_account", dict(payload={**DRAFT, "action": "add", "host": "imap.example.com:993"}), db)
    assert bad["status"] == "failed"
    assert _call("delete_account", {"account_id": account["id"]}, db)["value"]["deleted"] is True
    assert _call("list_accounts", {}, db)["value"]["mailboxes"] == []
    assert _call("list_sources", {}, db)["value"] == []


def test_cursors_are_plugin_owned_and_scoped_to_mailbox(tmp_path):
    db = tmp_path / "email.db"
    first = _call("save_account", dict(payload=DRAFT), db)["value"]
    second = _call("save_account", dict(payload={**DRAFT, "action": "add", "folder": "Sent"}), db)["value"]
    assert first["source_account_id"] != second["source_account_id"]
    assert _call("get_cursors", {"account_id": first["id"]}, db)["value"] == {}
    done = _call("set_cursors", {"account_id": first["id"], "cursors": {"imap_uid": "7", "imap_uidvalidity": "9"}}, db)
    assert done["value"] == {"imap_uid": "7", "imap_uidvalidity": "9"}
    assert _call("get_cursors", {"account_id": second["id"]}, db)["value"] == {}
    assert _call("set_cursors", {"account_id": first["id"], "cursors": {"imap_uid": 8}}, db)["error"]["code"] == "invalid_argument"
    assert _call("reset_cursors", {"account_id": first["id"]}, db)["value"]["reset"] is True
    assert _call("get_cursors", {"account_id": first["id"]}, db)["value"] == {}
    sources = _call("list_sources", {}, db)["value"]
    assert {s["account_id"] for s in sources} == {first["source_account_id"], second["source_account_id"]}


def test_legacy_mailbox_json_is_adopted_once(tmp_path):
    db, legacy = tmp_path / "email.db", tmp_path / "mailbox.json"
    legacy.write_text(json.dumps({"version": 2, "mailboxes": [
        {"id": "m1", "enabled": True, **DRAFT},
        {"id": "m2", "enabled": False, **{**DRAFT, "folder": "Sent"}},
    ]}), encoding="utf-8")
    listed = _call("list_accounts", {}, db, legacy_mailbox_path=legacy)["value"]["mailboxes"]
    assert [m["id"] for m in listed] == ["m1", "m2"] and [m["enabled"] for m in listed] == [True, False]
    assert SECRET not in json.dumps(listed)
    # Deleting after adoption is not undone by re-reading the old file.
    _call("delete_account", {"account_id": "m1"}, db, legacy_mailbox_path=legacy)
    again = _call("list_accounts", {}, db, legacy_mailbox_path=legacy)["value"]["mailboxes"]
    assert [m["id"] for m in again] == ["m2"]
    assert _call("fetch_messages", {"account_id": "m2"}, db)["error"]["message"] == "邮箱未启用"


def test_environment_defaults_apply_only_until_first_write(tmp_path, monkeypatch):
    db = tmp_path / "email.db"
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "env@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "envpw")
    listed = _call("list_accounts", {}, db)["value"]
    assert [m["id"] for m in listed["mailboxes"]] == ["environment"] and listed["configured"]
    _call("delete_account", {"account_id": "environment"}, db)
    assert _call("list_accounts", {}, db)["value"]["mailboxes"] == []


def test_connection_failures_are_structured_and_hide_password(tmp_path):
    db = tmp_path / "email.db"
    refused = _call("test_connection", dict(payload=DRAFT), db)
    assert refused["status"] == "failed" and refused["error"]["code"] == "invalid_argument"
    assert SECRET not in json.dumps(refused)
    saved = _call("save_account", dict(payload=DRAFT), db)["value"]
    folders = _call("list_folders", {"account_id": saved["id"]}, db)
    assert folders["status"] == "failed" and SECRET not in json.dumps(folders)
    both = _call("list_folders", {"account_id": saved["id"], "payload": DRAFT}, db)
    assert both["error"]["code"] == "invalid_argument"
    fetched = _call("fetch_messages", {"account_id": saved["id"]}, db)
    assert fetched["status"] == "failed" and SECRET not in json.dumps(fetched)
    assert _call("fetch_messages", {"account_id": "nope"}, db)["error"]["code"] == "not_found"
    unknown = _call("fetch_messages", {"account_id": saved["id"], "bogus": 1}, db)
    assert unknown["error"]["code"] == "invalid_argument"


def test_withdrawn_background_purpose_blocks_fetch_but_not_settings(tmp_path):
    db = tmp_path / "email.db"
    saved = _call("save_account", dict(payload=DRAFT), db)["value"]
    email_gateway.set_email_purposes({"interactive", "read"})
    assert _call("list_accounts", {}, db)["status"] == "succeeded"
    with pytest.raises(PermissionError, match="purpose not authorized"):
        _call("fetch_messages", {"account_id": saved["id"]}, db, purpose="background")
    assert _call("fetch_messages", {"account_id": saved["id"]}, db)["status"] == "failed"  # read purpose still allowed


def test_migration_entry_applies_and_verifies(tmp_path):
    path = (WORKSPACE_ROOT / "backend" / "migrate.py").resolve()
    spec = importlib.util.spec_from_file_location("stella_email_migrate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
        for name in [n for n in sys.modules if n == "domain" or n.startswith("domain.")]:
            del sys.modules[name]
    handle = {"dbPath": str(tmp_path / "email.db")}
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
    session = PluginSession(Path(store.current_package("stella.email")["path"]),
                            source_label="local-cache", registry=DEFAULT_REGISTRY)
    try:
        assert session.start()["initialize"]["pluginId"] == "stella.email"
        listed = session.invoke("list_accounts", {"_dataHandle": {"dbPath": str(tmp_path / "email.db")}})
        assert listed["status"] == "succeeded" and listed["value"]["mailboxes"] == []
    finally:
        session.dispose()


def test_official_catalog_digest_matches_package():
    from core.plugins.distribution import verify_package_digest

    catalog = SIBLING_ROOT.parents[1] / "catalog" / "official.json"
    if not catalog.is_file():
        pytest.skip("Stella-Plugins checkout not present")
    entry = next(e for e in json.loads(catalog.read_text())["plugins"] if e["pluginId"] == "stella.email")
    assert verify_package_digest(SIBLING_ROOT, entry["sha256"])


# ---- facade / Application port --------------------------------------------

def _patch_paths(monkeypatch, tmp_path):
    from core.services import email_facade

    monkeypatch.setattr(email_facade, "_paths", lambda: (tmp_path / "email.db", tmp_path / "mailbox.json"))


def test_application_port_routes_email_via_plugin_and_requires_flag(tmp_path, monkeypatch):
    from application.api import Application
    from common.runtime_identity import RuntimeIdentity, use_identity

    _patch_paths(monkeypatch, tmp_path)
    with use_identity(RuntimeIdentity(agent_id="a", user_id="u")):
        port = Application.port("email")
        saved = port.save_account(DRAFT)
        assert [m["id"] for m in port.list_accounts()["mailboxes"]] == [saved["id"]]
        assert port.set_cursors(saved["id"], {"imap_uid": "3"}) == {"imap_uid": "3"}
        with pytest.raises(KeyError):
            port.get_account("missing")
        with pytest.raises(ValueError):
            port.save_account({**DRAFT, "action": "add", "password": ""})
        monkeypatch.delenv("STELLA_EMAIL_PLUGIN")
        with pytest.raises(RuntimeError, match="stella.email"):
            Application.port("email")


def test_facade_legacy_names_and_source_adapter(tmp_path, monkeypatch):
    from core.services import email_facade

    _patch_paths(monkeypatch, tmp_path)
    facade = email_facade.EmailPluginFacade()
    saved = facade.save_mailbox(DRAFT)
    assert facade.public_mailboxes()["configured"] is True
    sources = email_facade.email_sources()
    assert [(s.name, s.account_id, s.mailbox_id) for s in sources] == [
        ("email", saved["source_account_id"], saved["id"])]
    with pytest.raises(ValueError):
        sources[0].fetch({"since": "2026-09-08T00:00:00Z"})  # refused port -> failure propagates, no secrets
    facade.delete_mailbox(saved["id"])
    assert email_facade.email_sources() == []


def test_source_adapter_maps_plugin_items_without_holding_credentials():
    from core.services.email_facade import EmailPluginSource

    seen = {}

    class Stub:
        def fetch_messages(self, mailbox_id, **kwargs):
            seen.update(mailbox_id=mailbox_id, **kwargs)
            return {"items": [{"source": "email", "source_id": "<m1>", "account_id": "imap-x", "title": "t",
                               "payload": {"body": "b"}}], "cursors": {"imap_uid": "5"}, "errors": []}

    source = EmailPluginSource(mailbox_id="m1", account_id="imap-x", facade=Stub())
    result = source.fetch({"imap_uid": "4", "since": "S", "until": "U", "refresh_existing_content": "1"})
    assert seen == {"mailbox_id": "m1", "cursors": {"imap_uid": "4"}, "refresh_existing_content": True,
                    "since": "S", "until": "U"}
    assert result.cursors == {"imap_uid": "5"} and result.items[0].source_id == "<m1>"
    assert not hasattr(source, "_password")


# ---- vendored domain with a fake IMAP server (in-process) ------------------

def _raw(msgid, subject):
    msg = RfcMessage()
    msg["From"] = "Ada <ada@example.com>"
    msg["Subject"] = subject
    msg["Date"] = "Tue, 8 Sep 2026 22:00:00 +0000"
    msg["Message-ID"] = msgid
    msg.set_content("请确认合同")
    return msg.as_bytes()


class FakeImap:
    def __init__(self, messages, uidvalidity=b"77", folders=(b'(\\HasNoChildren) "/" "INBOX"', b'(\\Noselect) "/" "[Gmail]"')):
        self.messages = messages
        self.untagged_responses = {"UIDVALIDITY": [uidvalidity]}
        self.folders = list(folders)
        self.searches = []
        self.logged_out = False

    def capability(self):
        return "OK", [b"IMAP4rev1"]

    def list(self):
        return "OK", self.folders

    def select(self, folder, readonly=True):
        return ("OK", [b"2"]) if folder == "INBOX" else ("NO", [b"nope " + SECRET.encode()])

    def uid(self, command, *args):
        if command == "SEARCH":
            self.searches.append(args)
            floor = int(args[2].split(":")[0]) if args[1] == "UID" else 0
            return "OK", [" ".join(str(u) for u in sorted(self.messages) if u >= floor).encode()]
        return "OK", [(b"1 (BODY[] {n}", self.messages[int(args[0])]), b")"]

    def logout(self):
        self.logged_out = True


def _service(tmp_path, client):
    service_module, _ = _load_vendored()
    return service_module.EmailService(tmp_path / "email.db", opener=lambda: client)


def test_fetch_proposes_cursors_and_does_not_advance_until_committed(tmp_path):
    client = FakeImap({1: _raw("<a@x>", "旧邮件"), 2: _raw("<b@x>", "新邮件")})
    service = _service(tmp_path, client)
    account = service.save_account(DRAFT)
    first = service.fetch_messages(account["id"], since="2026-09-08T00:00:00Z")
    assert [i["source_id"] for i in first["items"]] == ["<a@x>", "<b@x>"]
    assert first["cursors"] == {"imap_uid": "2", "imap_uidvalidity": "77"} and first["errors"] == []
    assert first["account_id"] == account["source_account_id"] and client.logged_out
    assert "body" in first["items"][0]["payload"] and SECRET not in json.dumps(first)
    # Not committed: the same messages are offered again.
    assert len(service.fetch_messages(account["id"], since="2026-09-08T00:00:00Z")["items"]) == 2
    service.set_cursors(account["id"], first["cursors"])
    client.messages[3] = _raw("<c@x>", "更新")
    second = service.fetch_messages(account["id"])
    assert [i["source_id"] for i in second["items"]] == ["<c@x>"]
    assert second["cursors"]["imap_uid"] == "3"
    # UIDVALIDITY change discards the stale UID cursor.
    client.untagged_responses["UIDVALIDITY"] = [b"88"]
    assert len(service.fetch_messages(account["id"], since="2026-09-08T00:00:00Z")["items"]) == 3


def test_test_connection_and_folders_use_fake_server_and_hide_unselectable(tmp_path):
    client = FakeImap({})
    service = _service(tmp_path, client)
    checked = service.test_connection(DRAFT)
    assert checked["connected"] and checked["folder_accessible"]
    assert [f["name"] for f in checked["folders"]] == ["INBOX"]
    assert [f["name"] for f in service.list_folders(payload=DRAFT)["folders"]] == ["INBOX"]
    account = service.save_account(DRAFT)
    assert service.list_folders(account["id"])["selected"] == "INBOX"
    blocked = service.test_connection({**DRAFT, "folder": "Missing"})
    assert blocked["folder_accessible"] is False and SECRET not in blocked["message"]
    service.save_account({"id": account["id"], "folder": "Missing", "password": "********"})
    with pytest.raises(ValueError) as error:
        service.fetch_messages(account["id"])
    assert SECRET not in str(error.value)
