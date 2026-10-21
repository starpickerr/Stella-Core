"""MCP transport adapter for elearning; business code is owned by its Server."""

from core.mcp.managed import enabled, invoke

ELEARNING_METHOD_PARAMS = {
    "get_settings": (),
    "get_cursors": (),
    "list_courses": (),
    "fetch": ("since", "until", "course_ids", "offset", "limit"),
    "fetch_source": ("cursors", "since", "until"),
    "list_files": ("course_ids", "file_ids", "file_extensions", "offset", "limit"),
    "save_settings": ("payload",),
    "delete_settings": (),
    "save_file_sync_settings": ("root",),
    "test_connection": ("payload",),
    "set_cursors": ("cursors",),
    "drain_audit_events": (),
    "sync_files": (
        "course_ids",
        "file_ids",
        "file_extensions",
        "layout",
        "offset",
        "limit",
    ),
}


def elearning_mcp_enabled():
    return enabled("elearning")


def invoke_elearning(method, params, *, purpose=None):
    if method not in ELEARNING_METHOD_PARAMS:
        raise ValueError("Unknown elearning method")
    return invoke("elearning", method, params, purpose=purpose)
