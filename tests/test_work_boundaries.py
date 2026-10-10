"""Private Work folders stay isolated even under Full Access."""

import os
from urllib.parse import quote

import pytest

from agent.permission.gateway import DecisionKind, Scope, SecurityGateway
from agent.workspace import project_store
from agent.workspace.context import resolve_context
from agent.workspace.shares import create_share, revoke_share


@pytest.fixture
def work(tmp_path, monkeypatch):
    root = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: root)
    monkeypatch.setattr("agent.workspace.shares._manifest_file", lambda: tmp_path / "shares.json")
    monkeypatch.setattr(project_store, "_store_file", lambda: str(tmp_path / "projects.json"))
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")
    return root


def _check(tool, args, cwd, session="recipient"):
    return SecurityGateway.check("full-access", tool, args, cwd=str(cwd),
                                 scope=Scope(write_roots=(str(cwd),)),
                                 session_id=session, agent_id="alpha")


def test_other_session_and_automation_are_private_even_in_full_access(work):
    owner = resolve_context("owner", "alpha", ensure=True)
    recipient = resolve_context("recipient", "alpha", ensure=True)
    task = resolve_context("owner", "alpha", task_id="task", ensure=True)
    (owner.root / "secret.txt").write_text("secret")
    (task.root / "task.txt").write_text("task")
    assert _check("read", {"path": str(recipient.root / "own.txt")}, recipient.root).allowed
    for path in (owner.root / "secret.txt", task.root / "task.txt", work / "sessions",
                 work / "shared"):
        for tool in ("read", "write", "ls", "search_files"):
            assert _check(tool, {"path": str(path)}, recipient.root).kind is DecisionKind.DENY
    alias = recipient.root / "alias"
    alias.symlink_to(owner.root, target_is_directory=True)
    assert _check("read", {"path": str(alias / "secret.txt")}, recipient.root).kind is DecisionKind.DENY


def test_exact_share_read_write_and_revoke(work):
    owner = resolve_context("owner", "alpha", ensure=True)
    recipient = resolve_context("recipient", "alpha", ensure=True)
    (owner.root / "shared.txt").write_text("shared")
    share = create_share("owner", "alpha", "shared.txt", "recipient", "read")
    path = share["path"]
    assert _check("read", {"path": path}, recipient.root).allowed
    assert _check("write", {"path": path}, recipient.root).kind is DecisionKind.DENY
    assert _check("read", {"path": os.path.dirname(path)}, recipient.root).kind is DecisionKind.DENY
    assert _check("read", {"path": path}, recipient.root, session="stranger").kind is DecisionKind.DENY
    writable = create_share("owner", "alpha", "shared.txt", "recipient", "write")
    assert _check("write", {"path": writable["path"]}, recipient.root).allowed
    revoke_share(share["id"], "owner", "alpha")
    assert _check("read", {"path": path}, recipient.root).kind is DecisionKind.DENY


def test_browser_file_navigation_and_shell_static_path_obey_boundary(work):
    owner = resolve_context("owner", "alpha", ensure=True)
    recipient = resolve_context("recipient", "alpha", ensure=True)
    path = owner.root / "secret.txt"
    path.write_text("secret")
    url = "file://" + quote(str(path))
    assert _check("browser", {"action": "navigate", "url": url}, recipient.root).kind is DecisionKind.DENY
    assert _check("bash", {"command": f"cat {path}"}, recipient.root).kind is DecisionKind.DENY


def test_pending_approval_fingerprint_changes_with_share_version(work):
    owner = resolve_context("owner", "alpha", ensure=True)
    recipient = resolve_context("recipient", "alpha", ensure=True)
    (owner.root / "shared.txt").write_text("shared")
    share = create_share("owner", "alpha", "shared.txt", "recipient", "read")
    from agent.permission.gateway import _fingerprint

    args = {"path": share["path"]}
    old = _fingerprint("read", args, "recipient", None, "alpha", str(recipient.root), Scope())
    revoke_share(share["id"], "owner", "alpha")
    new = _fingerprint("read", args, "recipient", None, "alpha", str(recipient.root), Scope())
    assert old != new


def test_desktop_raw_and_preview_paths_require_the_named_session_grant(work):
    from channel.desktop import desktop_channel as desktop

    owner = resolve_context("owner", "alpha", ensure=True)
    resolve_context("recipient", "alpha", ensure=True)
    path = owner.root / "secret.txt"
    path.write_text("secret")
    assert not desktop._is_path_allowed(str(path), "recipient", "alpha")
    assert desktop._is_path_allowed(str(path), "owner", "alpha")
    assert not desktop._is_path_allowed(str(path))
    shared = create_share("owner", "alpha", "secret.txt", "recipient", "read")
    assert desktop._is_path_allowed(shared["path"], "recipient", "alpha")
    assert not desktop._is_path_allowed(str((work / "shared" / shared["id"])), "recipient", "alpha")
    revoke_share(shared["id"], "owner", "alpha")
    assert not desktop._is_path_allowed(shared["path"], "recipient", "alpha")


def test_desktop_signed_preview_rechecks_share_revocation(work, monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import urlparse
    from channel.desktop import desktop_channel as desktop

    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "secret.txt").write_text("secret")
    shared = create_share("owner", "alpha", "secret.txt", "recipient", "read")
    monkeypatch.setattr(desktop, "_get_preview_secret", lambda: b"test-only-secret")
    monkeypatch.setattr(desktop.web, "header", lambda *args: None)
    class NotFound(Exception):
        pass
    monkeypatch.setattr(desktop.web, "notfound", lambda: NotFound())
    token_path = urlparse(desktop._build_preview_url(shared["path"], "recipient", "alpha")).path
    path_info = token_path.removeprefix("/preview/")
    assert desktop.PreviewHandler().GET(path_info) == b"secret"
    revoke_share(shared["id"], "owner", "alpha")
    with pytest.raises(NotFound):
        desktop.PreviewHandler().GET(path_info)

    monkeypatch.setattr(desktop, "_require_auth", lambda: None)
    monkeypatch.setattr(desktop.web, "input", lambda **kwargs: SimpleNamespace(
        path=str(owner.root / "secret.txt"), session="recipient", agent="alpha"))
    with pytest.raises(NotFound):
        desktop.FileServeHandler().GET()


def test_share_manifest_is_not_a_generic_file_tool_target(work):
    from agent.workspace.shares import _manifest_file

    manifest = str(_manifest_file())
    recipient = resolve_context("recipient", "alpha", ensure=True)
    for tool in ("read", "write", "edit", "send"):
        assert _check(tool, {"path": manifest}, recipient.root).kind is DecisionKind.DENY
