"""Todo categories rename and delete without breaking the task hierarchy."""

from stella_tasks_domain.service import TodoService


def test_todo_category_rename_keeps_hierarchy(tmp_path, scheduler_store):
    todos = TodoService(tmp_path / "todos.db", tmp_path / "calendar.db", scheduler_store=scheduler_store)
    category = todos.create_category({"name": "学习"})
    parent = todos.set_todo_category(todos.create_todo({"title": "课程"})["id"], category["id"])
    child = todos.set_todo_category(todos.add_subtask(parent["id"], {"title": "作业"})["id"], category["id"])
    todos.update_category(category["id"], {"name": "大学学习"})
    parent = todos.get_todo(parent["id"])
    child = todos.get_todo(child["id"])
    assert parent["list_name"] == child["list_name"] == "大学学习"
    assert parent["category_id"] == child["category_id"] == category["id"]
    assert child["parent_id"] == parent["id"]
    todos.delete_category(category["id"])
    assert todos.get_todo(parent["id"])["title"] == "课程"
    assert todos.get_todo(parent["id"])["category_id"] is None

