from agent.workspace import project_store
from agent.permission.gateway import Scope, SecurityGateway


def test_ordinary_and_project_chats_have_distinct_workspaces(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")
    monkeypatch.setattr(project_store, "projects_root", lambda: str(tmp_path / "projects"))
    first = project_store.create_project("first")
    second = project_store.create_project("second")
    assert project_store.get_project_dir("ordinary") is None
    assert project_store.set_project_dir("one", first) == first
    assert project_store.set_project_dir("two", second) == second
    assert project_store.get_project_map() == {"one": first, "two": second}
    project_store.rename_project(first, "Renamed")
    assert project_store.display_name_for(first) == "Renamed"
    assert not SecurityGateway.check("workspace-write", "write", {"path": second + "/file"}, cwd=first, scope=Scope(write_roots=(first,)))
    assert project_store.delete_project(first) == 1
    assert project_store.get_project_dir("one") is None
    assert project_store.get_project_dir("two") == second
    assert project_store.get_project_dir("ordinary") is None
