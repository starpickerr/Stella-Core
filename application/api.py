"""One user-scoped entry for desktop CRUD, agent tools and automation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from common.runtime_identity import RuntimeIdentity, current_identity, use_identity


@dataclass(frozen=True)
class RequestContext:
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    source: str = "desktop"
    channel_type: str = ""
    receiver: str = ""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    idempotency_key: Optional[str] = None

    @classmethod
    def ambient(cls, source="desktop"):
        identity = current_identity()
        return cls(user_id=identity.user_id, agent_id=identity.agent_id,
                   session_id=identity.session_id, source=source)


_METHODS = {
    "calendar": frozenset({
        "categories", "create_category", "get_category", "update_category", "delete_category",
        "get_event", "list_events", "create_event", "update_event", "delete_event",
        "import_china_holidays", "create_special_date", "import_special_dates",
        "ingest_briefing_revision",
    }),
    "todos": frozenset({
        "create_todo", "get_todo", "update_todo", "delete_todo", "complete_todo", "complete_checklist_item",
        "list_todos", "list_todos_focus", "claim_due_todo_notifications", "claim_desktop_reminders",
        "acknowledge_desktop_reminder", "list_uncertain_reminders",
        "retry_uncertain_reminder", "ingest_briefing_revision",
    }),
    "bills": frozenset({
        "list_ledger", "list_ledger_between", "get_ledger", "create_ledger",
        "update_ledger", "delete_ledger", "list_statements", "get_statement",
    }),
    "briefing": frozenset({
        "list_briefings", "get_briefing", "get_revision", "start_briefing",
        "complete_briefing", "update_item_status", "upsert_source_item", "list_rules",
        "get_rule", "create_rule", "update_rule", "delete_rule", "get_cursor", "set_cursor",
    }),
}


class _Port:
    def __init__(self, domain, context):
        if domain not in _METHODS:
            raise ValueError(f"unknown business domain: {domain}")
        if context.user_id and (context.user_id in (".", "..") or
                                "/" in context.user_id or "\\" in context.user_id):
            raise ValueError("invalid user identity")
        self.domain = domain
        self.context = context
        identity = RuntimeIdentity(agent_id=context.agent_id, user_id=context.user_id,
                                   session_id=context.session_id, run_id=current_identity().run_id)
        self.identity = identity
        with use_identity(identity):
            if domain == "calendar":
                from agent.calendar import CalendarService
                self._service = CalendarService()
            elif domain == "todos":
                from agent.todos import TodoService
                self._service = TodoService()
            elif domain == "bills":
                from agent.bills.service import BillsService
                self._service = BillsService()
            else:
                from agent.briefing.service import BriefingService
                self._service = BriefingService()

    @property
    def store(self):
        if self.domain != "briefing":
            raise AttributeError("store is only used by the briefing pipeline")
        return self._service.store

    def __getattr__(self, name):
        if name not in _METHODS[self.domain]:
            raise AttributeError(name)

        def call(*args, **kwargs):
            with use_identity(self.identity):
                return getattr(self._service, name)(*args, **kwargs)
        return call


class Application:
    @staticmethod
    def port(domain, context=None):
        return _Port(domain, context or RequestContext.ambient())

    @staticmethod
    def command(domain, name, params=None, context=None):
        """Typed domain command for scheduled business actions."""
        commands = {
            "calendar": {"CreateEvent": "create_event", "UpdateEvent": "update_event",
                         "DeleteEvent": "delete_event"},
            "todos": {"CreateTodo": "create_todo", "UpdateTodo": "update_todo",
                      "CompleteTodo": "complete_todo", "DeleteTodo": "delete_todo"},
            "bills": {"PostLedgerEntry": "create_ledger", "UpdateLedgerEntry": "update_ledger",
                      "DeleteLedgerEntry": "delete_ledger"},
        }
        method = commands.get(domain, {}).get(name)
        if not method:
            raise ValueError(f"unknown business command: {domain}.{name}")
        args = params if isinstance(params, list) else [params or {}]
        request = context or RequestContext.ambient()
        operation_id = request.idempotency_key or uuid.uuid4().hex
        with use_identity(RuntimeIdentity(agent_id=request.agent_id, user_id=request.user_id,
                                          session_id=request.session_id, run_id=current_identity().run_id)):
            from agent.runtime.tool_invocation import permission_denial
            action = {"create_ledger": "add", "update_ledger": "update", "delete_ledger": "delete",
                      "create_todo": "create", "update_todo": "update", "complete_todo": "complete",
                      "delete_todo": "delete", "create_event": "create", "update_event": "update",
                      "delete_event": "delete"}[method]
            denial = permission_denial(domain, {"action": action}, agent_id=request.agent_id,
                                       session_id=request.session_id)
            if denial:
                raise PermissionError(denial)
            store = None
            if request.idempotency_key:
                from application.operations import OperationStore
                store = OperationStore()
                completed, cached = store.admit(operation_id, store.payload_hash(domain, name, args))
                if completed:
                    return {"operation_id": operation_id, "value": cached,
                            "side_effects": "completed"}
            try:
                value = getattr(Application.port(domain, request), method)(*args)
            except Exception as exc:
                if store:
                    store.unknown(operation_id, exc)
                raise
            if store:
                store.finish(operation_id, value)
        return {"operation_id": operation_id, "value": value,
                "side_effects": "completed"}
