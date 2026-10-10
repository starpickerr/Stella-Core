"""Exact Work file shares survive restart and revoke without leaking siblings."""

import pytest

from agent.workspace import project_store
from agent.workspace.context import resolve_context
from agent.workspace.shares import create_share, list_shares, revoke_share, share_access


@pytest.fixture
def work(tmp_path, monkeypatch):
    root = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: root)
    monkeypatch.setattr("agent.workspace.shares._manifest_file", lambda: tmp_path / "shares.json")
    monkeypatch.setattr(project_store, "_store_file", lambda: str(tmp_path / "projects.json"))
    return root


def test_share_one_file_read_and_write_without_exposing_sibling(work):
    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "report.txt").write_text("draft")
    (owner.root / "private.txt").write_text("secret")
    shared = create_share("owner", "alpha", "report.txt", "recipient", "read")
    assert shared["path"].startswith(str(work / "shared"))
    assert len(list_shares("recipient", "alpha")) == 1
    assert list_shares("unrelated", "alpha") == []
    assert share_access(shared["path"], "recipient", "alpha") == "read"
    assert share_access(shared["path"], "unrelated", "alpha") is None
    assert share_access(str(owner.root / "private.txt"), "recipient", "alpha") is None
    assert share_access(str(work / "shared" / shared["id"] / "private.txt"), "recipient", "alpha") is None
    assert shared["path"] in [row["path"] for row in list_shares("owner", "alpha")]

    writable = create_share("owner", "alpha", "report.txt", "editor", "write")
    assert share_access(writable["path"], "editor", "alpha") == "write"
    assert share_access(writable["path"], "recipient", "alpha") is None


def test_revoke_removes_recipient_grant_but_keeps_owner_data(work):
    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "file.txt").write_text("keep")
    shared = create_share("owner", "alpha", "file.txt", "recipient", "read")
    assert revoke_share(shared["id"], "owner", "alpha")["active"] is False
    assert share_access(shared["path"], "recipient", "alpha") is None
    assert list_shares("recipient", "alpha") == []
    assert list_shares("owner", "alpha")[0]["active"] is False
    assert (work / "shared" / shared["id"] / "file.txt").read_text() == "keep"
    with pytest.raises(PermissionError):
        revoke_share(shared["id"], "recipient", "alpha")


def test_share_rejects_directory_traversal_and_symlinks(work, tmp_path):
    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "safe.txt").write_text("safe")
    (owner.root / "folder").mkdir()
    (owner.root / "link.txt").symlink_to(tmp_path / "outside")
    for path in ("folder", "../other/file", "link.txt", str(owner.root / "safe.txt")):
        with pytest.raises(ValueError):
            create_share("owner", "alpha", path, "recipient", "read")
    with pytest.raises(ValueError):
        create_share("owner", "alpha", "safe.txt", "recipient", "invalid")


def test_share_recipients_are_scoped_to_agent_and_ids_are_valid(work):
    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "file.txt").write_text("data")
    shared = create_share("owner", "alpha", "file.txt", "recipient", "read")
    assert list_shares("recipient", "beta") == []
    assert share_access(shared["path"], "recipient", "beta") is None
    with pytest.raises(ValueError):
        create_share("owner", "alpha", "file.txt", "../escape", "read")


def test_share_source_changed_to_symlink_after_validation_is_rejected(work, tmp_path, monkeypatch):
    from agent.workspace import shares

    owner = resolve_context("owner", "alpha", ensure=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    link = owner.root / "file.txt"
    link.symlink_to(outside)
    monkeypatch.setattr(shares, "_regular_source", lambda root, relative: link)
    with pytest.raises(ValueError):
        create_share("owner", "alpha", "file.txt", "recipient", "read")
    assert list_shares("recipient", "alpha") == []


def test_replacing_shared_copy_with_symlink_does_not_expand_grant(work, tmp_path):
    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "file.txt").write_text("safe")
    shared = create_share("owner", "alpha", "file.txt", "recipient", "read")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    target = work / "shared" / shared["id"] / "file.txt"
    target.unlink()
    target.symlink_to(outside)
    assert share_access(shared["path"], "recipient", "alpha") is None


def test_authenticated_share_api_creates_lists_and_revokes(work, monkeypatch):
    import json
    from types import SimpleNamespace
    from channel.desktop import desktop_channel as channel

    owner = resolve_context("owner", "alpha", ensure=True)
    (owner.root / "report.txt").write_text("draft")
    monkeypatch.setattr(channel, "_require_auth", lambda: None)
    monkeypatch.setattr(channel.web, "header", lambda *args: None)
    monkeypatch.setattr(channel.web, "input", lambda **kwargs: SimpleNamespace(
        session="recipient", agent="alpha"))
    body = [{"session": "owner", "agent": "alpha", "path": "report.txt",
             "recipient": "recipient", "access": "read"}]
    monkeypatch.setattr(channel.web, "data", lambda: json.dumps(body[-1]).encode())
    created = json.loads(channel.WorkspaceSharesHandler().POST())
    assert created["status"] == "success"
    share = created["share"]
    received = json.loads(channel.WorkspaceSharesHandler().GET())
    assert [row["id"] for row in received["shares"]] == [share["id"]]
    body.append({"session": "owner", "agent": "alpha", "id": share["id"]})
    revoked = json.loads(channel.WorkspaceShareRevokeHandler().POST())
    assert revoked["status"] == "success"
    assert json.loads(channel.WorkspaceSharesHandler().GET())["shares"] == []
