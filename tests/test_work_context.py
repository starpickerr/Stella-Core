"""Canonical Work paths are stable, lazy, and do not strand legacy files."""

import pytest

from agent.workspace import project_store
from agent.workspace.context import copy_legacy_file, list_legacy_files, resolve_context


@pytest.fixture
def work_root(tmp_path, monkeypatch):
    work = tmp_path / "work"
    monkeypatch.setattr("agent.workspace.context.personal_work_dir", lambda **kwargs: work)
    monkeypatch.setattr(project_store, "_store_file", lambda: str(tmp_path / "projects.json"))
    return work


def test_external_chat_id_uses_a_stable_safe_directory(work_root):
    external_id = "wxid:person@im.chat"
    first = resolve_context(external_id, "alpha")
    second = resolve_context(external_id, "alpha")
    assert first.root == second.root
    assert first.root.parent == work_root / "sessions" / "alpha"
    assert first.root.name != external_id
    assert "/" not in first.root.name


def test_sessions_projects_and_tasks_get_distinct_lazy_roots(work_root, tmp_path):
    first = resolve_context("one", "alpha")
    second = resolve_context("two", "alpha")
    other_agent = resolve_context("one", "beta")
    task = resolve_context("one", "alpha", task_id="scheduled")
    assert first.root == work_root / "sessions" / "alpha" / "one"
    assert second.root == work_root / "sessions" / "alpha" / "two"
    assert other_agent.root == work_root / "sessions" / "beta" / "one"
    assert task.root == work_root / "automations" / "alpha" / "scheduled"
    assert task.root == resolve_context("different-run", "alpha", task_id="scheduled").root
    assert first.kind == "session" and task.kind == "automation"
    assert not work_root.exists()

    project = tmp_path / "project"
    project.mkdir()
    project_store.set_project_dir("one", str(project), "alpha")
    assert resolve_context("one", "alpha").root == project
    assert resolve_context("one", "alpha", task_id="scheduled").root == project
    assert resolve_context("one", "alpha").kind == "project"
    assert resolve_context("two", "alpha", ensure=True).root.is_dir()


@pytest.mark.parametrize("bad", ["", "..", "../escape", "a/b", "a\\b", ".", "bad space", "x" * 81])
def test_context_rejects_unsafe_ids(work_root, bad):
    for kwargs in ({"session_id": bad, "agent_id": "alpha"},
                   {"session_id": "ok", "agent_id": bad},
                   {"session_id": "ok", "agent_id": "alpha", "task_id": bad}):
        with pytest.raises(ValueError, match="invalid"):
            resolve_context(**kwargs)
    assert not work_root.exists()


def test_missing_bound_project_is_an_error(work_root, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    project_store.set_project_dir("one", str(project), "alpha")
    project.rmdir()
    assert project_store.get_project_binding("one", "alpha") == str(project)
    with pytest.raises(FileNotFoundError, match="project"):
        resolve_context("one", "alpha")
    with pytest.raises(FileNotFoundError, match="project"):
        resolve_context("one", "alpha", task_id="scheduled")
    assert not work_root.exists()


def test_legacy_copy_is_explicit_and_preserves_original(work_root):
    old = work_root / "notes" / "draft.txt"
    old.parent.mkdir(parents=True)
    old.write_text("old data")
    hidden = work_root / "sessions" / "alpha" / "other" / "secret.txt"
    hidden.parent.mkdir(parents=True)
    hidden.write_text("private")
    assert list_legacy_files() == ["notes/draft.txt"]
    context = resolve_context("one", "alpha")
    copied = copy_legacy_file("notes/draft.txt", context)
    assert copied == context.root / "notes" / "draft.txt"
    assert copied.read_text() == old.read_text() == "old data"
    copied.write_text("new data")
    assert old.read_text() == "old data"
    with pytest.raises(FileExistsError):
        copy_legacy_file("notes/draft.txt", context)
    with pytest.raises(ValueError):
        copy_legacy_file("sessions/alpha/other/secret.txt", context)
    with pytest.raises(ValueError):
        copy_legacy_file("../elsewhere", context)


def test_legacy_copy_rejects_symlink_sources(work_root, tmp_path):
    work_root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (work_root / "link.txt").symlink_to(secret)
    assert list_legacy_files() == []
    with pytest.raises(ValueError):
        copy_legacy_file("link.txt", resolve_context("one", "alpha"))


def test_legacy_copy_does_not_create_through_target_symlink(work_root, tmp_path):
    old = work_root / "notes" / "folder" / "draft.txt"
    old.parent.mkdir(parents=True)
    old.write_text("old data")
    target = resolve_context("one", "alpha", ensure=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (target.root / "notes").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        copy_legacy_file("notes/folder/draft.txt", target)
    assert not (outside / "folder").exists()
