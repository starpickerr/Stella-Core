"""Built-in tool catalog stays complete without changing what agents receive."""

import json

import agent.tools as tools
from agent.tools.catalog import build_catalog, tools_payload
from agent.tools.tool_manager import ToolManager


EXCLUDED = {"BaseTool", "ToolManager", "McpTool"}


def _export_ids():
    ids = []
    for class_name in tools.__all__:
        if class_name in EXCLUDED:
            continue
        ids.append(getattr(tools, class_name).name)
    return ids


def test_catalog_ids_match_builtin_exports_once():
    exported = _export_ids()
    catalog_ids = [item["id"] for item in build_catalog(loaded_ids=set())]
    assert "memory_search" in catalog_ids
    assert "memory_get" in catalog_ids
    assert catalog_ids.count("memory_search") == 1
    assert set(catalog_ids) == set(exported)
    assert len(catalog_ids) == len(set(catalog_ids))
    assert not any(item_id.startswith("mcp") for item_id in catalog_ids)


def test_every_entry_has_bilingual_copy_and_no_secrets():
    for item in build_catalog(loaded_ids={"read"}):
        assert item["id"]
        for field in ("title", "intro", "detail"):
            assert item[field]["zh"].strip()
            assert item[field]["en"].strip()
            assert item[field]["zh"] != item[field]["en"]
        assert "description" not in item
        blob = json.dumps(item, ensure_ascii=False).lower()
        assert "api_key" not in blob
        assert "sk-" not in blob
        assert "token" not in blob


def test_unavailable_tools_stay_listed_with_a_reason():
    rows = {item["id"]: item for item in build_catalog(loaded_ids={"read"})}
    assert rows["read"]["available"] is True
    assert rows["read"]["reason"] is None
    assert rows["web_fetch"]["available"] is False
    assert rows["web_fetch"]["reason"]["zh"]
    assert rows["web_fetch"]["reason"]["en"]
    assert rows["memory_search"]["available"] is False
    assert "记忆" in rows["memory_search"]["reason"]["zh"]
    assert rows["memory_get"]["reason"]["en"]


def test_listing_the_catalog_does_not_register_memory_tools():
    manager = ToolManager()
    manager.load_tools()
    before = set(manager.tool_classes)
    build_catalog(loaded_ids=before)
    assert set(manager.tool_classes) == before
    assert "memory_search" not in manager.tool_classes
    payload = tools_payload()
    assert payload["status"] == "success"
    assert "memory_search" in {item["id"] for item in payload["tools"]}
    again = ToolManager()
    again.load_tools()
    assert "memory_search" not in again.tool_classes
