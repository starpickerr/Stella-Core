"""Retain persisted restrictions while retiring the old plugin transports.

No new plugin grants are issued. Existing restrictions remain authoritative;
request resource scopes are forwarded as MCP metadata, never Agent arguments.
"""

from core.plugins.authz import DEFAULT_AUTHZ
from core.plugins.caller import (
    current_consumer_plugin,
    current_invocation_purpose,
    current_delegation,
    current_caller_origin,
    user_grant_ref,
)
from core.plugins.resources import invocation_resources

CAPABILITIES = {
    "email": {
        "test_connection": "email.connect",
        "list_folders": "email.connect",
        "fetch_messages": "email.fetch",
        "save_account": "email.write",
        "delete_account": "email.write",
        "set_cursors": "email.write",
        "reset_cursors": "email.write",
    },
    "elearning": {
        "save_settings": "elearning.write",
        "delete_settings": "elearning.write",
        "save_file_sync_settings": "elearning.write",
        "test_connection": "elearning.write",
        "set_cursors": "elearning.write",
        "drain_audit_events": "elearning.write",
        "sync_files": "elearning.files",
    },
}
PURPOSES = {
    "elearning": {
        "list_courses": "discover",
        "test_connection": "discover",
        "fetch": "read",
        "list_files": "read",
        "fetch_source": "background",
        "get_cursors": "background",
        "set_cursors": "background",
        "sync_files": "sync",
    },
    "email": {
        "list_sources": "read",
        "get_cursors": "read",
        "set_cursors": "read",
        "reset_cursors": "read",
        "fetch_messages": "read",
    },
}


def check(domain, method, arguments, user, metadata, purpose=None):
    plugin_id = "stella." + domain
    ref = user_grant_ref(domain + "-default-grant", user)
    grant = DEFAULT_AUTHZ.get(ref)
    children = DEFAULT_AUTHZ.scoped_grants(user, plugin_id=plugin_id)
    if grant is None and not children:
        return None
    from common.runtime_identity import current_identity

    identity = current_identity()
    delegation = current_delegation()
    purpose = purpose or PURPOSES[domain].get(method, "interactive")
    if (
        identity.task_id
        or current_caller_origin() == "job"
        or current_invocation_purpose() == 'background'
        or (delegation and delegation["purpose"] == "background")
    ):
        purpose = "background"
    capability = CAPABILITIES[domain].get(method, domain + ".read")
    if grant is not None:
        # Managed parent grants can be scope containers without capabilities.
        DEFAULT_AUTHZ.check(
            grant_ref=ref,
            plugin_id=plugin_id,
            user_id=user,
            required_capabilities=() if children else [capability],
            purpose=purpose,
            generation=1,
            context_generation=1,
        )
    if not children:
        return None
    scope = dict(
        grant_ref=ref,
        plugin_id=plugin_id,
        user_id=user,
        consumer_plugin_id=current_consumer_plugin() or plugin_id,
        method=method,
        required_capabilities=[capability],
        purpose="background" if purpose == "background" else "interactive",
    )
    DEFAULT_AUTHZ.check_scoped(**scope, resources=[])
    resources = invocation_resources(plugin_id, method, arguments, user, metadata)
    DEFAULT_AUTHZ.check_scoped(**scope, resources=resources)
    return {"resourceScope": {"userId": user, "resources": resources}}
