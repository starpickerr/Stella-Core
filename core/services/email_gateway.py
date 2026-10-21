"""MCP transport adapter for email; business code is owned by its Server."""

from core.mcp.managed import enabled, invoke

EMAIL_METHOD_PARAMS = {
    "list_accounts": (),
    "get_account": ("account_id",),
    "list_sources": (),
    "get_cursors": ("account_id",),
    "test_connection": ("payload",),
    "list_folders": ("account_id", "payload"),
    "fetch_messages": (
        "account_id",
        "since",
        "until",
        "cursors",
        "refresh_existing_content",
        "lookback_days",
    ),
    "save_account": ("payload",),
    "delete_account": ("account_id",),
    "set_cursors": ("account_id", "cursors"),
    "reset_cursors": ("account_id",),
}


def email_mcp_enabled():
    return enabled("email")


def invoke_email(method, params, *, purpose=None):
    if method not in EMAIL_METHOD_PARAMS:
        raise ValueError("Unknown email method")
    return invoke("email", method, params, purpose=purpose)
