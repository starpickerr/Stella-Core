from agent.workspace import project_store
from agent.permission.gateway import Scope, SecurityGateway
from channel.desktop.desktop_channel import _annotate_sessions_with_projects


def test_ordinary_and_project_chats_have_distinct_workspaces(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")
    monkeypatch.setattr(project_store, "projects_root", lambda: str(tmp_path / "projects"))
    first = project_store.create_project("first")
    second = project_store.create_project("second")
    assert {project["path"] for project in project_store.list_known_projects()} == {first, second}
    assert project_store.get_project_dir("ordinary") is None
    assert project_store.set_project_dir("one", first) == first
    assert project_store.set_project_dir("two", second) == second
    assert project_store.get_project_map() == {"one": first, "two": second}
    result = {"sessions": [{"session_id": "one"}, {"session_id": "ordinary"}]}
    store = type("Store", (), {"list_session_ids": lambda self, channel_type: ["one", "two", "ordinary"]})()
    _annotate_sessions_with_projects(store, result, None)
    assert result["sessions"][0]["project"]["path"] == first
    assert result["sessions"][1]["project"] is None
    assert {item["path"]: item["conversation_count"] for item in result["projects"]} == {first: 1, second: 1}
    assert project_store.set_order(["__default__", second, first]) == [second, first]
    assert project_store.get_order() == [second, first]
    project_store.rename_project(first, "Renamed")
    assert project_store.display_name_for(first) == "Renamed"
    assert not SecurityGateway.check("workspace-write", "write", {"path": second + "/file"}, cwd=first, scope=Scope(write_roots=(first,)))
    assert project_store.delete_project(first) == 1
    assert {project["path"] for project in project_store.list_known_projects()} == {second}
    assert project_store.get_project_dir("one") is None
    assert project_store.get_project_dir("two") == second
    assert project_store.get_project_dir("ordinary") is None


def test_empty_projects_remain_after_recent_picker_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("common.state_dir.shared_root", lambda: tmp_path / "state")
    monkeypatch.setattr(project_store, "projects_root", lambda: str(tmp_path / "projects"))
    paths = {project_store.create_project(f"project-{index}") for index in range(21)}

    assert len(project_store.list_recents()) == project_store.MAX_RECENTS
    assert {project["path"] for project in project_store.list_known_projects()} == paths
