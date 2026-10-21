"""Security-owned data access view; legacy storage routes forward to Data Service."""
from core.data import storage
from agent.permission.audit import record


def data_access_inventory(connection_rows=None):
    from agent.permission.center import connections
    transfers = []
    for row in (connection_rows if connection_rows is not None else connections()):
        if not row.get("configured"):
            continue
        transfers.append({
            "id": row["id"],
            "name": row["name"],
            "available": bool(row.get("available", row.get("connected"))),
            "note": {
                "zh": "仅在使用相关功能时，可能向该服务发送授权范围内的请求数据。",
                "en": "When you use this feature, authorized request data may be sent to this service.",
            },
        })
    transfers.insert(0, {
        "id": "model_api",
        "name": "AI Model API",
        "available": True,
        "note": {
            "zh": "对话内容、必要的工具结果与上下文可能发送给当前配置的模型服务。",
            "en": "Chat content, necessary tool results, and context may be sent to the configured model provider.",
        },
    })
    from core.data.runtime import current_service
    resources=[{key:source[key] for key in ['id','name','provider','account_id','connection'] if key in source}
               for source in current_service().list_sources()]
    from agent.permission.mcp_access import inventory as inherited_grants
    return {"available": True, "external_transfers": transfers,'resources':resources, "inherited_grants": inherited_grants()}



def inventory():
    """Compatibility response; storage has one implementation in Core Data."""
    from agent.permission.audit import _path
    result=storage.inventory()
    result['categories'].append(storage._category('security_activity',{'zh':'安全活动','en':'Security activity'},
        _path(),retention={'zh':'安全服务管理访问审计。','en':'Access audit managed by Security.'},actions=['clear_security_activity']))
    return {**result,**data_access_inventory()}


def cleanup(action):
    if action == "clear_security_activity":
        from agent.permission.audit import _path as audit_path
        path = audit_path()
        if path.exists():
            path.write_text("", encoding="utf-8")
        record(operation="cleanup", resource="security activity", decision="policy_change",
               reason="Cleared security activity log.")
        return {"status": "success", "removed": 1 if path.exists() else 0}
    return storage.cleanup(action)
