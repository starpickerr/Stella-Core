"""Data Service operations use Security's current policy, never a second ACL."""

from agent.permission.gateway import Capability, register_tool
from agent.runtime.tool_invocation import permission_denial
from core.mcp.managed import native_user_action


def authorize(operation, source_id):
    readonly = operation == "metadata"
    name = "data_inspect" if readonly else "data_manage"
    register_tool(name, Capability.READ if readonly else Capability.WORKSPACE_WRITE)
    reason = permission_denial(
        name,
        {"action": operation, "source_id": source_id},
        noninteractive=True,
        user_action=native_user_action(True, name, None),
    )
    if reason:
        raise PermissionError(reason)
