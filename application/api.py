"""One user-scoped entry for desktop CRUD, agent tools and automation."""

from __future__ import annotations

import uuid
import threading
from dataclasses import dataclass, field
from typing import Optional

from common.runtime_identity import RuntimeIdentity, current_identity, use_identity


_apple_managers = {}
_apple_managers_lock = threading.RLock()


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
        "get_event", "list_events", "create_event", "update_event", "delete_event", "set_event_category",
        "upsert_external_event",
        "exclude_occurrence",
        "import_china_holidays", "create_special_date", "import_special_dates",
        "ingest_briefing_revision",
    }),
    "todos": frozenset({
        "create_todo", "get_todo", "update_todo", "delete_todo", "complete_todo", "complete_checklist_item",
        "change_todo_status", "add_subtask", "move_todo", "add_dependency", "remove_dependency",
        "list_todos", "list_todos_focus", "claim_due_todo_notifications", "claim_desktop_reminders",
        "acknowledge_desktop_reminder", "list_uncertain_reminders",
        "retry_uncertain_reminder", "queue_scheduled_reminder", "ingest_briefing_revision",
        "upsert_external_todo", "delete_external_todo",
        "categories", "create_category", "get_category", "update_category", "delete_category",
        "set_todo_category",
    }),
    "bills": frozenset({
        "list_ledger", "list_ledger_between", "get_ledger", "create_ledger",
        "update_ledger", "delete_ledger", "list_statements", "get_statement",
    }),
    "briefing": frozenset({
        "list_briefings", "get_briefing", "get_revision", "start_briefing", "briefing_for_date",
        "complete_briefing", "update_item_status", "upsert_source_item", "list_rules",
        "get_rule", "create_rule", "update_rule", "delete_rule", "get_cursor", "set_cursor",
        "build_source_item", "update_action", "list_action_rules", "create_action_rule", "delete_action_rule",
        "get_preferences", "update_preferences", "get_action_targets", "get_overview",
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
                from core.services.bills_gateway import bills_plugin_enabled
                if bills_plugin_enabled():
                    from core.services.bills_facade import BillsPluginFacade
                    self._service = BillsPluginFacade()
                else:
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
                mutates = name.startswith(('create_', 'update_', 'delete_', 'complete_', 'change_', 'add_', 'remove_', 'move_', 'import_', 'ingest_', 'upsert_', 'withdraw_', 'start_', 'set_'))
                run_id = current_identity().run_id
                if not mutates or not run_id:
                    return getattr(self._service, name)(*args, **kwargs)
                from agent.runtime.tool_invocation import current_tool_call_id
                from agent.runtime.run_record import RunRecord
                from application.operations import OperationStore
                operation_id = uuid.uuid4().hex
                operations = OperationStore()
                operations.admit(operation_id, operations.payload_hash(self.domain, name, [args, kwargs]))
                record = RunRecord()
                record.event(run_id, "business_operation_started", tool_call_id=current_tool_call_id(), operation_id=operation_id)
                try:
                    result = getattr(self._service, name)(*args, **kwargs)
                except Exception as exc:
                    operations.unknown(operation_id, str(exc))
                    record.event(run_id, "business_operation_unknown", tool_call_id=current_tool_call_id(), operation_id=operation_id)
                    raise
                operations.finish(operation_id, result)
                record.event(run_id, "business_operation_completed", tool_call_id=current_tool_call_id(), operation_id=operation_id)
                return result
        return call


class Application:
    @staticmethod
    def _apple_manager(kind):
        from common.state_dir import calendar_db, todos_db

        if kind == "calendar":
            from agent.calendar.apple_sync import AppleCalendarSync
            manager_type = AppleCalendarSync
            path = calendar_db().with_name("apple_sync.db")
        elif kind == "reminders":
            from agent.todos.apple_sync import AppleReminderSync
            manager_type = AppleReminderSync
            path = todos_db().with_name("apple_reminders.db")
        else:
            raise ValueError("unknown Apple integration")
        key = (kind, str(path.resolve()))
        with _apple_managers_lock:
            if key not in _apple_managers:
                _apple_managers[key] = manager_type(db_path=path)
            return _apple_managers[key]

    @staticmethod
    def apple_calendar():
        return Application._apple_manager("calendar")

    @staticmethod
    def apple_reminders():
        return Application._apple_manager("reminders")

    @staticmethod
    def reset_apple_managers():
        """Drop cached managers in isolated tests, stopping their watchers first."""
        with _apple_managers_lock:
            for manager in _apple_managers.values():
                manager.stop_auto()
            _apple_managers.clear()

    @staticmethod
    def dispatch_todo_reminder(todo_id, expected_at, context):
        """Resume the todo outbox only from a scheduler handoff."""
        if context.source != "scheduler":
            raise PermissionError("todo reminder dispatch is reserved for scheduler")
        from agent.todos import TodoService
        with use_identity(RuntimeIdentity(agent_id=context.agent_id, user_id=context.user_id,
                                          session_id=context.session_id, run_id=current_identity().run_id)):
            return TodoService().dispatch_scheduled_reminder(todo_id, expected_at)

    @staticmethod
    def scheduler(store=None):
        """Use one scheduler mutation contract from desktop and Agent callers."""
        from agent.scheduler.mutations import SchedulerMutations
        if store is None:
            from agent.todos.scheduler_link import default_scheduler_store
            store = default_scheduler_store()
        return SchedulerMutations(store)

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
                      "CompleteTodo": "complete_todo", "DeleteTodo": "delete_todo",
                      "ChangeTodoStatus": "change_todo_status", "AddSubtask": "add_subtask",
                      "MoveTodo": "move_todo", "AddTodoDependency": "add_dependency",
                      "RemoveTodoDependency": "remove_dependency",
                      "QueueTodoReminder": "queue_scheduled_reminder"},
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
                      "delete_todo": "delete", "change_todo_status": "update",
                      "add_subtask": "create", "move_todo": "update",
                      "add_dependency": "update", "remove_dependency": "update",
                      "create_event": "create", "update_event": "update",
                      "delete_event": "delete"}.get(method)
            if method == "queue_scheduled_reminder":
                if request.source != "scheduler":
                    raise PermissionError("todo reminder handoff is reserved for scheduler")
            else:
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
