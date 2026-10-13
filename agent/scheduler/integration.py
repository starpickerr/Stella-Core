"""Wire the scheduler domain into AgentBridge: init, execute, attach."""

import os
import threading
from typing import Dict
from config import conf
from common.log import logger
from common.utils import expand_path
from agent.scheduler.outcome import ExecutionOutcome
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType

# Backward-compatible aliases for the configured default agent.
_scheduler_service = None
_task_store = None
_scheduler_services: Dict[str, object] = {}
_task_stores: Dict[str, object] = {}
# Module-level lock to guard idempotent initialization across threads
_init_lock = threading.RLock()


def _resolve_workspace(workspace_root: str = None, agent_id: str = None):
    """An explicit workspace wins, then an explicit agent_id, then the routed
    identity. An agent_id that does not resolve raises: falling back to the
    default workspace here would silently file one Agent's tasks under
    another."""
    if workspace_root is not None:
        return os.path.realpath(expand_path(str(workspace_root)))
    from common.runtime_identity import current_identity
    from common.state_dir import state_root

    identity = current_identity()
    if agent_id:
        identity = identity.derive(agent_id=agent_id)
    return str(state_root(identity))


def _resolve_working_dir(agent_id: str = None):
    from common.runtime_identity import current_identity
    from common.state_dir import personal_work_dir
    return str(personal_work_dir(current_identity().derive(agent_id=agent_id)))


def init_scheduler(agent_bridge, workspace_root: str = None, agent_id: str = None) -> bool:
    """
    Initialize scheduler service (idempotent).

    Safe to call multiple times and from multiple threads: only the first
    successful call creates the singleton ``SchedulerService`` + background
    scanning thread. Subsequent calls return immediately.

    Args:
        agent_bridge: AgentBridge instance

    Returns:
        True if scheduler is initialized (newly created or already running)
    """
    global _scheduler_service, _task_store
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    agent_id = agent_bridge.agent_registry.get(agent_id).id

    # Fast path: already initialized and running
    service = _scheduler_services.get(workspace_root)
    if service is not None and getattr(service, "running", False):
        return True

    with _init_lock:
        # Re-check under the lock to avoid races where multiple threads
        # passed the fast-path check before any of them acquired the lock.
        service = _scheduler_services.get(workspace_root)
        if service is not None and getattr(service, "running", False):
            return True

        try:
            from agent.scheduler.store import TaskStore
            from agent.scheduler.automation_store import AutomationStore
            from agent.scheduler.service import SchedulerService

            from common.state_dir import scheduler_file

            store_path = str(scheduler_file(base=workspace_root))

            # Create task store (reuse if already created)
            task_store = _task_stores.get(workspace_root)
            if task_store is None:
                task_store = (AutomationStore(store_path, agent_id)
                              if os.environ.get("STELLA_DESKTOP") == "1"
                              else TaskStore(store_path))
                _task_stores[workspace_root] = task_store
                logger.debug(f"[Scheduler] Task store initialized: {store_path}")

            # Create execute callback. Returns True on success, False to ask
            # the scheduler to retry on the next tick (e.g. channel not yet
            # ready right after process start).
            def execute_task_callback(task: dict):
                # Scheduler threads carry no identity of their own. Binding it
                # here is the counterpart to chat_channel._handle: leaf code
                # reached from a task (ToolManager, tmp_dir, memory) then lands
                # in this Agent's workspace rather than the default one's.
                from common.runtime_identity import identity_scope
                from agent.scheduler.conversation import prepare_run
                from agent.scheduler.outcome import ExecutionOutcome

                try:
                    owner_user_id = task.get("owner_user_id") or None
                    with identity_scope(agent_id=agent_id, user_id=owner_user_id):
                        task = prepare_run(task, agent_id)
                    owner_session_id = ((task.get("action") or {}).get("execution_session_id") or
                                        (task.get("action") or {}).get("notify_session_id"))
                    from agent.runtime.tool_invocation import scheduled_permission_scope
                    with identity_scope(agent_id=agent_id, user_id=owner_user_id,
                                        session_id=owner_session_id, task_id=str(task.get("id") or "") or None,
                                        execution_session_id=owner_session_id), scheduled_permission_scope(
                                            task.get("run_permission_mode")):
                        action = task.get("action", {})
                        action_type = action.get("type")
                        channel_type = action.get("channel_type", "unknown")
                        receiver = action.get("receiver", "")

                        silent = (action_type == "application_command" or
                                  action_type in ("agent_task", "tool_call", "skill_call") and action.get("silent", False))
                        persist_in_chat = "conversation_mode" in action
                        if not silent and not task.get("notification_route") and not persist_in_chat and not _is_channel_ready(channel_type, receiver, agent_id):
                            logger.warning(
                                f"[Scheduler] Task {task.get('id')}: channel "
                                f"'{channel_type}' not ready for receiver={receiver} "
                                f"(no inbound msg cached since restart?); deferring"
                            )
                            return False

                        if action_type == "agent_task":
                            return _execute_agent_task(task, agent_bridge, agent_id)
                        elif action_type == "application_command":
                            return _execute_application_command(task, agent_id)
                        elif action_type == "send_message":
                            return _execute_send_message(task, agent_bridge, agent_id)
                        elif action_type == "tool_call":
                            return _execute_tool_call(task, agent_bridge, agent_id, cancel_event=service.stop_event)
                        elif action_type == "skill_call":
                            return _execute_skill_call(task, agent_bridge, agent_id)
                        else:
                            logger.warning(f"[Scheduler] Unknown action type: {action_type}")
                            return ExecutionOutcome("failed", f"Unknown action type: {action_type}")
                except ValueError as e:
                    logger.warning(f"[Scheduler] Task {task.get('id')} has no valid conversation scope: {e}")
                    return ExecutionOutcome("failed", str(e))
                except Exception as e:
                    logger.error(f"[Scheduler] Error executing task {task.get('id')}: {e}")
                    return False

            # Create scheduler service
            service = SchedulerService(task_store, execute_task_callback)
            service.start()
            _scheduler_services[workspace_root] = service
            if agent_id == agent_bridge.agent_registry.default_agent_id:
                _scheduler_service = service
                _task_store = task_store

            logger.info(
                f"[Scheduler] Service initialized for agent={agent_id}, "
                f"workspace={workspace_root}"
            )
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to initialize scheduler: {e}")
            return False


def _is_channel_ready(
    channel_type: str, receiver: str, agent_id: str = None
) -> bool:
    """Best-effort readiness probe for outbound channels.

    Returns False when we know the send will drop (e.g. weixin not yet
    logged in, web session has no polling queue), so the scheduler can
    defer instead of consuming the task. Unknown channels return True
    to preserve previous behaviour.
    """
    if not channel_type or channel_type == "unknown":
        return False
    try:
        if channel_type == "weixin":
            from agent.scheduler.delivery import runtime_channel
            channel = runtime_channel(channel_type)
        else:
            from channel.channel_factory import create_channel
            channel = create_channel(channel_type)
        if channel is None:
            return False

        if channel_type == "weixin":
            if getattr(channel, "login_status", None) != "logged_in":
                return False
            tokens = getattr(channel, "_context_tokens", None)
            if not tokens or receiver not in tokens:
                return False
            return True

        if channel_type == "web":
            if hasattr(channel, "has_session_queue"):
                return channel.has_session_queue(receiver, agent_id)
            queues = getattr(channel, "session_queues", None)
            if not queues or receiver not in queues:
                return False
            return True

        return True
    except Exception as e:
        logger.warning(f"[Scheduler] Channel readiness check failed for {channel_type}: {e}")
        return False


def get_task_store(workspace_root: str = None, agent_id: str = None):
    """Get the task store owned by one agent workspace."""
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    return _task_stores.get(workspace_root)


def get_scheduler_service(workspace_root: str = None, agent_id: str = None):
    """Get the scheduler service owned by one agent workspace."""
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    return _scheduler_services.get(workspace_root)


def reset_scheduler_services(stop: bool = True) -> None:
    """Stop and forget all scheduler services, primarily for reloads/tests."""
    global _scheduler_service, _task_store
    with _init_lock:
        if stop:
            for service in list(_scheduler_services.values()):
                try:
                    service.stop()
                except Exception:
                    pass
        _scheduler_services.clear()
        _task_stores.clear()
        _scheduler_service = None
        _task_store = None


def _remember_delivered_output(
    agent_bridge,
    task: dict,
    channel_type: str,
    content: str,
    agent_id: str = None,
) -> bool:
    """Persist desktop output; message channels keep best-effort injection.

    Uses notify_session_id (the real chat session_id stored at task creation time)
    so that group chats correctly associate the output with the user's conversation.
    Falls back to receiver for backward compatibility with old tasks.

    Per-action-type behaviour:
        - agent_task / tool_call / skill_call: gated by ``scheduler_inject_to_session``
          (default True). These produce AI-generated content worth remembering.
        - send_message: other channels additionally use
          ``scheduler_inject_send_message`` (default False). Desktop task
          conversations always keep the delivered text.
    """
    if not content:
        return True
    action = task.get("action", {})
    action_type = action.get("type", "")

    # send_message defaults to NOT being injected; explicit opt-in via config.
    if action_type == "send_message" and "conversation_mode" not in action:
        if not conf().get("scheduler_inject_send_message", False):
            return True

    session_id = action.get("notify_session_id") or action.get("receiver")
    if not session_id:
        return False
    try:
        remember = getattr(agent_bridge, "remember_scheduled_output", None)
        if remember:
            conversation_store = None
            is_new = False
            if "conversation_mode" in action:
                from agent.memory import get_conversation_store
                from agent.registry import get_agent_registry
                profile = get_agent_registry().get(agent_id)
                conversation_store = get_conversation_store(profile.workspace)
                is_new = session_id not in conversation_store.list_session_ids(channel_type="web")
            task_desc = action.get("task_description") or action.get("content", "")
            kwargs = {
                "channel_type": channel_type,
                "task_description": task_desc,
            }
            if hasattr(agent_bridge, "agent_registry"):
                kwargs["agent_id"] = agent_id
                if "conversation_mode" in action:
                    kwargs["force"] = True
                    kwargs["require_existing"] = action.get("conversation_mode") == "source"
            remember(session_id, str(content), **kwargs)
            if is_new and conversation_store and action.get("conversation_mode") in ("reuse", "new"):
                title = task.get("name") or "Scheduled task"
                if action.get("conversation_mode") == "new":
                    from datetime import datetime
                    title += " · " + datetime.now().strftime("%Y-%m-%d %H:%M")
                conversation_store.rename_session(session_id, title)
            return True
    except Exception as e:
        logger.warning(
            f"[Scheduler] Failed to remember delivered output for {session_id}: {e}"
        )
    return False


def _send_checked(channel, reply, context):
    context["scheduled_delivery"] = True
    result = channel.send(reply, context)
    if result is False or (isinstance(result, dict) and result.get("success") is False):
        raise RuntimeError("Channel rejected scheduled delivery")
    return result


def _channel_for_delivery(channel_type):
    if channel_type == "weixin":
        from agent.scheduler.delivery import runtime_channel
        return runtime_channel(channel_type)
    from channel.channel_factory import create_channel
    return create_channel(channel_type)


def _dispatch_explicit_route(task, content, agent_id=None, store=None):
    """Send cached output through a persisted, user selected route."""
    from datetime import datetime, timedelta
    from agent.scheduler.dispatch import dispatch_notification
    route = task.get("notification_route")
    job_run_id = task.get("job_run_id")
    store = store or get_task_store(agent_id=agent_id)
    if not job_run_id or not store or not hasattr(store, "begin_delivery"):
        return ExecutionOutcome("failed", "Durable notification delivery requires an active job run")
    expires_at = None
    scheduled_at = task.get("next_run_at")
    if scheduled_at and not task.get("manual_run"):
        due = datetime.fromisoformat(scheduled_at)
        expires_at = due.astimezone() + timedelta(hours=24)
    result = dispatch_notification(store, job_run_id, route, content, agent_id=agent_id,
                                   expires_at=expires_at)
    return _delivery_execution_outcome(result)


def _delivery_execution_outcome(result):
    if result is None:
        return True
    if result.status == "accepted":
        return True
    if result.status == "waiting" and result.error == "等待客户端确认通知":
        return True
    if result.status == "waiting" or (result.status == "failed" and result.retryable):
        return False
    if result.status == "unknown":
        return ExecutionOutcome("outcome_unknown", result.error)
    return ExecutionOutcome("failed", result.error or result.status)


def _execute_agent_task(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """
    Execute an agent_task action - let Agent handle the task.
    Returns True on successful delivery, False to retry next tick.
    """
    try:
        action = task.get("action", {})
        task_description = action.get("task_description")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not task_description:
            logger.error(f"[Scheduler] Task {task['id']}: No task_description specified")
            return ExecutionOutcome("failed", "task_description is required")
        
        if not receiver and not action.get("silent", False):
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return ExecutionOutcome("failed", "receiver is required")
        
        # Check for unsupported channels
        if channel_type == "dingtalk":
            logger.warning(f"[Scheduler] Task {task['id']}: DingTalk channel does not support scheduled messages (Stream mode limitation). Task will execute but message cannot be sent.")
        
        logger.info(f"[Scheduler] Task {task['id']}: Executing agent task '{task_description}'")

        # Wrap the raw description with an execution directive. The stored
        # description is often phrased as a rule ("every day at 08:00 send...").
        # Without this prefix the agent may treat it as a spec to acknowledge
        # instead of a task to run right now, especially after a mid-run failure.
        execution_prompt = (
            "这是一个定时任务的立即执行请求，当前已到执行时刻。"
            "请直接完成下面描述的任务并产出最终交付内容，"
            "无需复述、确认或讨论任务规则，不要输出任务指令或调试信息。"
            "若执行失败，返回简洁明确的失败说明。\n\n"
            f"任务描述：\n{task_description}"
        )
        if action.get("conversation_mode") == "source":
            from agent.scheduler.conversation import source_context
            recent = source_context(action, agent_id)
            if recent:
                execution_prompt += "\n\n绑定对话的最近上下文（供参考）：\n" + recent

        # Create a unique session_id for this scheduled task to avoid polluting user's conversation
        # Format: scheduler_<receiver>_<task_id> to ensure isolation
        from agent.scheduler.conversation import agent_session_id
        scheduler_session_id = agent_session_id(task)
        
        # Create context for Agent
        context = Context(ContextType.TEXT, execution_prompt)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id
        context["channel_type"] = channel_type
        context["execution_session_id"] = action.get("execution_session_id") or action.get("notify_session_id")
        context["task_id"] = str(task["id"])
        if task.get("job_run_id"):
            context["job_run_id"] = task["job_run_id"]
        
        # Channel-specific setup
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = action.get("receive_id_type") or ("chat_id" if is_group else "open_id")
            context["msg"] = None
        elif channel_type == "dingtalk":
            # DingTalk requires msg object, set to None for scheduled tasks
            context["msg"] = None
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
        elif channel_type == "wecom_bot":
            context["msg"] = None

        # Use Agent to execute the task
        # Mark this as a scheduled task execution to prevent recursive task creation
        context["is_scheduled_task"] = True
        
        try:
            from agent.scheduler.result_cache import load_output, save_output
            store = get_task_store(agent_id=agent_id)
            job_run_id = task.get("job_run_id")
            content = load_output(store, job_run_id)
            if content is None:
                # Scheduler sessions are isolated from the user's conversation.
                reply = agent_bridge.agent_reply(execution_prompt, context=context, on_event=None, clear_history=False)
                if getattr(reply, "type", None) == ReplyType.ERROR:
                    logger.error(f"[Scheduler] Task {task['id']}: Agent run failed; outcome needs review")
                    return ExecutionOutcome("failed", str(reply.content))
                content = reply.content if reply else ""
                save_output(store, job_run_id, content)
            reply = Reply(ReplyType.TEXT, content)

            if not (reply and reply.content):
                # Empty is a valid outcome: the task ran and decided there was
                # nothing worth reporting (conditional reminders, monitors with
                # no alert). Send nothing rather than a placeholder message.
                logger.info(
                    f"[Scheduler] Task {task['id']}: agent produced no content, nothing to send"
                )
                return True

            if action.get("silent", False):
                logger.info(
                    f"[Scheduler] Task {task['id']} executed successfully in silent mode"
                )
                return True

            if task.get("notification_route"):
                result = _dispatch_explicit_route(task, reply.content, agent_id, store)
                if result is not True:
                    return result
                _remember_delivered_output(agent_bridge, task, channel_type, reply.content, agent_id)
                return True

            channel = _channel_for_delivery(channel_type)
            if not channel:
                logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
                return False

            if channel_type == "web" and hasattr(channel, 'request_to_session'):
                request_id = context.get("request_id")
                if request_id:
                    channel.request_to_session[request_id] = receiver

            try:
                _send_checked(channel, reply, context)
            except Exception as e:
                logger.error(f"[Scheduler] Failed to send result: {e}")
                return False

            persisted = _remember_delivered_output(
                agent_bridge, task, channel_type, reply.content, agent_id
            )
            if "conversation_mode" in action and not persisted:
                return False
            logger.info(f"[Scheduler] Task {task['id']} executed successfully, result sent to {receiver}")
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute task via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            return ExecutionOutcome("outcome_unknown", str(e))

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_agent_task: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return ExecutionOutcome("outcome_unknown", str(e))


def _execute_send_message(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a send_message action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        content = action.get("content", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return ExecutionOutcome("failed", "receiver is required")
        
        # Create context for sending message
        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id
        context["channel_type"] = channel_type
        context["execution_session_id"] = action.get("execution_session_id") or action.get("notify_session_id")
        context["task_id"] = str(task["id"])
        
        # Channel-specific context setup
        if channel_type == "web":
            # Web channel needs request_id
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
            logger.debug(f"[Scheduler] Generated request_id for web channel: {request_id}")
        elif channel_type == "feishu":
            # Feishu channel: for scheduled tasks, send as new message (no msg_id to reply to)
            # Use chat_id for groups, open_id for private chats
            context["receive_id_type"] = action.get("receive_id_type") or ("chat_id" if is_group else "open_id")
            # Keep isgroup as is, but set msg to None (no original message to reply to)
            # Feishu channel will detect this and send as new message instead of reply
            context["msg"] = None
            logger.debug(f"[Scheduler] Feishu: receive_id_type={context['receive_id_type']}, is_group={is_group}, receiver={receiver}")
        elif channel_type == "dingtalk":
            # DingTalk channel setup
            context["msg"] = None
            # 如果是单聊，需要传递 sender_staff_id
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
                    logger.debug(f"[Scheduler] DingTalk single chat: sender_staff_id={sender_staff_id}")
                else:
                    logger.warning(f"[Scheduler] Task {task['id']}: DingTalk single chat message missing sender_staff_id")
        elif channel_type == "wecom_bot":
            context["msg"] = None
        elif channel_type == "qq":
            context["msg"] = None

        # Create reply
        reply = Reply(ReplyType.TEXT, content)
        if task.get("notification_route"):
            result = _dispatch_explicit_route(task, content, agent_id)
            if result is not True:
                return result
            _remember_delivered_output(agent_bridge, task, channel_type, content, agent_id)
            return True
        
        # Get channel and send
        channel = _channel_for_delivery(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            _send_checked(channel, reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send message: {e}")
            return False

        persisted = _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        if "conversation_mode" in action and not persisted:
            return False
        logger.info(f"[Scheduler] Task {task['id']} executed: sent message to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_send_message: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def _execute_application_command(task, agent_id=None):
    from application import Application, RequestContext
    from agent.runtime.run_record import RunRecord
    from agent.scheduler.outcome import ExecutionOutcome
    from common.runtime_identity import identity_scope
    import uuid
    action = task.get("action", {})
    base = RequestContext.ambient("scheduler")
    run_id = uuid.uuid4().hex
    record = RunRecord()
    record.create(run_id, job_run_id=task.get("job_run_id"), user_id=base.user_id,
                  agent_id=agent_id, session_id=base.session_id, source="scheduler")
    record.transition(run_id, "running")
    try:
        with identity_scope(run_id=run_id):
            context = RequestContext(user_id=base.user_id, agent_id=agent_id, session_id=base.session_id,
                source="scheduler", idempotency_key=task.get("job_run_id"))
            record.event(run_id, "tool_execution_start", operation_id=context.idempotency_key)
            result = Application.command(action.get("domain"), action.get("command"), action.get("params"), context)
            record.event(run_id, "tool_execution_end", operation_id=result["operation_id"])
            record.transition(run_id, "completed")
            if action.get("domain") == "todos" and action.get("command") == "QueueTodoReminder":
                todo_id, expected_at = action.get("params", [None, None])
                delivery = Application.dispatch_todo_reminder(todo_id, expected_at, context)
                return _delivery_execution_outcome(delivery)
            return True
    except Exception as exc:
        status = "failed" if isinstance(exc, (PermissionError, ValueError)) else "outcome_unknown"
        if isinstance(exc, PermissionError):
            record.event(run_id, "permission_denied")
        record.event(run_id, "tool_execution_end")
        record.transition(run_id, status, str(exc))
        logger.warning(
            "[Scheduler] Scheduled command failed: %s.%s %s",
            action.get("domain"), action.get("command"), exc,
        )
        return ExecutionOutcome(status, str(exc))


def _run_scheduled_tool(task, tool_name, tool_params, agent_id, cancel_event, store):
    """Record execution independently of the result's delivery attempts."""
    from agent.runtime.run_record import RunRecord
    from agent.runtime.tool_invocation import permission_denial
    from agent.scheduler.outcome import ExecutionOutcome
    from agent.scheduler.result_cache import save_output
    from agent.tools.tool_manager import ToolManager
    from common.runtime_identity import current_identity, identity_scope
    import uuid
    identity = current_identity()
    run_id = uuid.uuid4().hex
    record = RunRecord()
    action = task.get("action", {})
    source_session = action.get("execution_session_id") or action.get("notify_session_id")
    record.create(run_id, job_run_id=task.get("job_run_id"), user_id=identity.user_id,
                  agent_id=agent_id or identity.agent_id, session_id=source_session, source="scheduler")
    record.transition(run_id, "running")
    invoked = False
    tool_call_id = uuid.uuid4().hex
    try:
        from agent.runtime.tool_invocation import scheduled_permission_scope
        with identity_scope(run_id=run_id, session_id=source_session,
                            task_id=str(task["id"]), execution_session_id=source_session), scheduled_permission_scope(
                                task.get("run_permission_mode")):
            denial = permission_denial(tool_name, tool_params, agent_id=agent_id,
                session_id=source_session, workspace=_resolve_working_dir(agent_id=agent_id),
                noninteractive=True)
            if denial:
                record.event(run_id, "permission_denied")
                record.transition(run_id, "failed", denial)
                logger.warning("[Permission] Scheduled deny tool=%s: %s", tool_name, denial)
                return ExecutionOutcome("failed", denial)
            tool = ToolManager().create_tool(tool_name)
            if not tool:
                error = f"Tool '{tool_name}' not found"
                record.transition(run_id, "failed", error)
                logger.warning("[Scheduler] Scheduled tool not found: %s", tool_name)
                return ExecutionOutcome("failed", error)
            from agent.runtime.tool_invocation import execution_workspace
            cwd, _ = execution_workspace(source_session, agent_id, _resolve_working_dir(agent_id=agent_id))
            setter = getattr(tool, "set_cwd", None)
            if callable(setter):
                setter(cwd)
            else:
                tool.cwd = cwd
            tool.config = dict(getattr(tool, "config", {}) or {}, cwd=cwd)
            tool.current_context = Context(ContextType.TEXT, "", {"is_scheduled_task": True,
                "agent_id": agent_id, "session_id": source_session, "job_run_id": task.get("job_run_id")})
            tool.cancel_event = cancel_event
            record.event(run_id, "tool_execution_start", tool_call_id=tool_call_id)
            invoked = True
            from agent.runtime.tool_invocation import invocation_scope
            with invocation_scope(tool_call_id):
                result = tool.execute(tool_params)
            record.event(run_id, "tool_execution_end", tool_call_id=tool_call_id)
            content = result.result if hasattr(result, "result") else str(result)
            if getattr(result, "status", None) == "error":
                record.transition(run_id, "failed", str(content))
                retryable = (tool_name == "briefing" and tool_params.get("action") == "run" and
                             tool_params.get("operation", "create") == "create")
                logger.warning("[Scheduler] Scheduled tool failed: %s %s", tool_name, content)
                return ExecutionOutcome("failed", str(content), retryable=retryable)
            save_output(store, task.get("job_run_id"), content)
            record.transition(run_id, "completed")
            return content
    except Exception as exc:
        status = "outcome_unknown" if invoked else "failed"
        record.transition(run_id, status, str(exc))
        logger.warning("[Scheduler] Scheduled tool raised: %s %s", tool_name, exc)
        return ExecutionOutcome(status, str(exc))


def _execute_tool_call(task: dict, agent_bridge, agent_id: str = None, cancel_event=None) -> bool:
    """Execute a tool_call action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        tool_name = action.get("call_name") or action.get("tool_name")
        tool_params = action.get("call_params") or action.get("tool_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")
        silent = bool(action.get("silent", False))

        if not tool_name:
            logger.error(f"[Scheduler] Task {task['id']}: No tool_name specified")
            return ExecutionOutcome("failed", "tool name is required")
        if not receiver and not silent:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return ExecutionOutcome("failed", "receiver is required")

        from agent.scheduler.result_cache import load_output
        store = get_task_store(agent_id=agent_id)
        job_run_id = task.get("job_run_id")
        content = load_output(store, job_run_id)
        if content is None:
            from agent.runtime.session_run import SessionRun
            from common.runtime_identity import current_identity
            manager = getattr(agent_bridge, "_session_run", None)
            if manager is None:
                manager = SessionRun()
                if agent_bridge is not None:
                    agent_bridge._session_run = manager
            source = action.get("execution_session_id") or action.get("notify_session_id")
            with manager.enter(current_identity().user_id, agent_id, source or f"scheduler_{task['id']}"):
                content = _run_scheduled_tool(task, tool_name, tool_params, agent_id, cancel_event, store)
            from agent.scheduler.outcome import ExecutionOutcome
            if isinstance(content, ExecutionOutcome):
                return content
        if silent:
            return True
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        if task.get("notification_route"):
            result = _dispatch_explicit_route(task, content, agent_id, store)
            if result is not True:
                return result
            _remember_delivered_output(agent_bridge, task, channel_type, content, agent_id)
            return True

        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id
        context["channel_type"] = channel_type
        context["execution_session_id"] = action.get("execution_session_id") or action.get("notify_session_id")

        request_id = None
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = action.get("receive_id_type") or ("chat_id" if is_group else "open_id")
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        reply = Reply(ReplyType.TEXT, content)

        channel = _channel_for_delivery(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and request_id and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            _send_checked(channel, reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send tool result: {e}")
            return False

        persisted = _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        if "conversation_mode" in action and not persisted:
            return False
        logger.info(f"[Scheduler] Task {task['id']} executed: sent tool result to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_tool_call: {e}")
        from agent.scheduler.outcome import ExecutionOutcome
        return ExecutionOutcome("outcome_unknown", str(e))


def _execute_skill_call(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a resolved skill under the scheduled Agent's tool gate.
    Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        skill_name = action.get("call_name") or action.get("skill_name")
        skill_params = action.get("call_params") or action.get("skill_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = action.get("channel_type", "unknown")

        if not skill_name:
            logger.error(f"[Scheduler] Task {task['id']}: No skill_name specified")
            return ExecutionOutcome("failed", "skill name is required")
        if not receiver and not action.get("silent", False):
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return ExecutionOutcome("failed", "receiver is required")

        logger.info(f"[Scheduler] Task {task['id']}: Executing skill '{skill_name}'")

        from agent.scheduler.conversation import agent_session_id
        scheduler_session_id = agent_session_id(task)
        context = Context(ContextType.TEXT, "Scheduled skill execution")
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id
        context["channel_type"] = channel_type
        context["execution_session_id"] = action.get("execution_session_id") or action.get("notify_session_id")
        context["is_scheduled_task"] = True
        context["task_id"] = str(task["id"])
        if task.get("job_run_id"):
            context["job_run_id"] = task["job_run_id"]

        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = action.get("receive_id_type") or ("chat_id" if is_group else "open_id")
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        from agent.scheduler.result_cache import load_output, save_output
        store = get_task_store(agent_id=agent_id)
        job_run_id = task.get("job_run_id")
        content = load_output(store, job_run_id)
        if content is None:
            try:
                from agent.scheduler.skill_executor import SkillExecutor
                reply = SkillExecutor(agent_bridge).execute(
                    skill_name, skill_params, context, agent_id)
            except Exception as e:
                logger.error(f"[Scheduler] Failed to execute skill via Agent: {e}")
                return ExecutionOutcome("outcome_unknown", str(e))
            if getattr(reply, "type", None) == ReplyType.ERROR:
                logger.error(f"[Scheduler] Task {task['id']}: Skill run failed; outcome needs review")
                return ExecutionOutcome("failed", str(reply.content))
            content = reply.content if reply else ""
            save_output(store, job_run_id, content)

        if not content:
            logger.error(f"[Scheduler] Task {task['id']}: No result from skill execution")
            return True

        if action.get("silent", False):
            return True

        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        if task.get("notification_route"):
            result = _dispatch_explicit_route(task, content, agent_id, store)
            if result is not True:
                return result
            _remember_delivered_output(agent_bridge, task, channel_type, content, agent_id)
            return True

        channel = _channel_for_delivery(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            req_id = context.get("request_id")
            if req_id:
                channel.request_to_session[req_id] = receiver

        try:
            _send_checked(channel, Reply(ReplyType.TEXT, content), context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send skill result: {e}")
            return False

        persisted = _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        if "conversation_mode" in action and not persisted:
            return False
        logger.info(f"[Scheduler] Task {task['id']} executed: skill result sent to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_skill_call: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return ExecutionOutcome("outcome_unknown", str(e))


def attach_scheduler_to_tool(tool, context: Context = None):
    """
    Attach scheduler components to a SchedulerTool instance
    
    Args:
        tool: SchedulerTool instance
        context: Current context (optional)
    """
    if context:
        agent_id = context.get("agent_id")
        task_store = get_task_store(agent_id=agent_id)
        scheduler_service = get_scheduler_service(agent_id=agent_id)
        if task_store:
            tool.task_store = task_store
        if scheduler_service:
            tool.scheduler_service = scheduler_service
        tool.current_context = context
        
        channel_type = context.get("channel_type") or conf().get("channel_type", "unknown")
        if not tool.config:
            tool.config = {}
        tool.config["channel_type"] = channel_type
