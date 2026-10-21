"""Native administration of retained MCP grants in Security's existing store.

The old plugin identity is a persisted namespace, not an active plugin. No grants
are issued implicitly; restoring or changing a grant is an explicit owner action.
"""

from datetime import datetime, timezone
import json
from agent.permission.audit import record
from common.runtime_identity import current_identity
from core.plugins.authz import _expiry, _resource_key
from core.plugins.caller import plugin_user_id, user_grant_ref
from core.mcp.managed import native_user_action


def _native():
    identity = current_identity()
    if any(
        getattr(identity, key)
        for key in (
            "agent_id",
            "session_id",
            "run_id",
            "task_id",
            "execution_session_id",
        )
    ) or not native_user_action(True, "manage_mcp_access", None):
        raise PermissionError(
            "MCP access must be edited by the user in Security Center"
        )


def _owned():
    from core.mcp.authorization import DEFAULT_AUTHZ

    user = plugin_user_id()
    rows = []
    for domain in ("email", "elearning"):
        parent = DEFAULT_AUTHZ.get(user_grant_ref(domain + "-default-grant", user))
        if (
            parent is not None
            and parent.user_id == user
            and parent.plugin_id == "stella." + domain
        ):
            rows.append(parent)
        rows.extend(DEFAULT_AUTHZ.scoped_grants(user, plugin_id="stella." + domain))
    return rows


def inventory():
    _native()
    return [
        {
            "id": row.grant_ref,
            "server": row.plugin_id.removeprefix("stella."),
            "consumer": row.consumer_plugin_id,
            "capabilities": sorted(row.capabilities),
            "methods": sorted(row.methods),
            "purposes": sorted(row.purposes),
            "resources": [json.loads(raw) for raw in sorted(row.resources)],
            "valid_until": row.valid_until,
            "revoked": row.revoked,
            "revision": row.policy_revision,
            "scoped": bool(row.parent_ref),
        }
        for row in _owned()
    ]


def update(body):
    _native()
    if (
        not isinstance(body, dict)
        or set(body)
        - {"id", "revision", "revoked", "purposes", "resources", "valid_until"}
        or not isinstance(body.get("id"), str)
        or type(body.get("revision")) is not int
    ):
        raise ValueError("Invalid MCP grant update")
    row = next((row for row in _owned() if row.grant_ref == body["id"]), None)
    if row is None:
        raise PermissionError("Grant does not belong to this user or migrated MCP")
    changes = {
        key: value for key, value in body.items() if key not in {"id", "revision"}
    }
    if "revoked" in changes and type(changes["revoked"]) is not bool:
        raise ValueError("revoked must be a boolean")
    if "purposes" in changes:
        values = changes["purposes"]
        allowed = (
            {"interactive", "background"}
            if row.parent_ref
            else {"interactive", "background", "read", "discover", "sync", "any"}
        )
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(value, str) or value not in allowed for value in values
            )
        ):
            raise ValueError("Invalid grant purposes")
        changes["purposes"] = frozenset(values)
    if "resources" in changes:
        values = changes["resources"]
        if (
            not isinstance(values, list)
            or (row.parent_ref and not values)
            or (not row.parent_ref and values)
        ):
            raise ValueError("Invalid scoped resources")
        changes["resources"] = frozenset(_resource_key(value) for value in values)
    if "valid_until" in changes:
        value = changes["valid_until"]
        if value is not None and (
            not row.parent_ref
            or not isinstance(value, str)
            or _expiry(value) <= datetime.now(timezone.utc)
        ):
            raise ValueError(
                "Expiry must be a future timezone-aware date for a scoped grant"
            )
    from core.mcp.authorization import DEFAULT_AUTHZ

    DEFAULT_AUTHZ.update_owned(
        row.grant_ref, user_id=plugin_user_id(), revision=body["revision"], **changes
    )
    record(
        operation="update",
        resource="mcp:" + row.plugin_id.removeprefix("stella."),
        decision="policy_change",
        reason="User updated inherited MCP authorization in Security Center.",
    )
    return inventory()
