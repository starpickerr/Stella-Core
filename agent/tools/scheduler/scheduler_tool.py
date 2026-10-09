"""
Scheduler tool — let the agent create and manage timed tasks.

Thin adapter over ``agent.scheduler``: the same TaskStore / SchedulerService
the Web console, desktop, Feishu, and CLI talk to. This module only maps
model arguments onto that layer and formats replies for the conversation.
"""

import uuid
import json
from datetime import datetime
from typing import Optional

from agent.tools.base_tool import BaseTool, ToolResult
from agent.scheduler.cron import iter_cron
from bridge.context import Context
from common.log import logger


class SchedulerTool(BaseTool):
    """
    Tool for managing scheduled tasks (reminders, notifications, etc.)
    """
    
    name: str = "scheduler"
    description: str = (
        "创建、查询和管理定时任务（提醒、周期性任务等）。\n\n"
        "⚠️ 重要：仅当需要「定时/提醒/每天/每周/X分钟后/X点」等延迟或周期执行时才使用此工具。"
        "使用方法：\n"
        "- 创建：action='create', name='任务名', message/ai_task='内容', schedule_type='once/interval/cron', schedule_value='...'\n"
        "- 查询：action='list' / action='get', task_id='任务ID'\n"
        "- 管理：action='delete/enable/disable', task_id='任务ID'\n\n"
        "调度类型：\n"
        "- once: 一次性任务，支持相对时间(+5s,+10m,+1h,+1d)或ISO时间\n"
        "- interval: 固定间隔(秒)，如3600表示每小时\n"
        "- cron: cron表达式，5 位「分 时 日 月 周」（如 '0 8 * * *' 每天8点）或 6 位「秒 分 时 日 月 周」\n\n"
        "注意：'X秒后'用once+相对时间，'每X秒'用interval"
    )
    params: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "get", "update", "destinations", "delete", "enable", "disable"],
                "description": "操作类型: create(创建), list(列表), get(查询), delete(删除), enable(启用), disable(禁用)"
            },
            "task_id": {
                "type": "string",
                "description": "任务ID (用于 get/delete/enable/disable 操作)"
            },
            "name": {
                "type": "string",
                "description": "任务名称 (用于 create 操作)"
            },
            "message": {
                "type": "string",
                "description": "固定消息内容 (与ai_task二选一)"
            },
            "ai_task": {
                "type": "string",
                "description": (
                    "任务描述 (与message二选一)，描述到点时需要 Agent 执行的任务，例如执行什么操作、交付什么内容，"
                    "无需重复声明调度时间（由 schedule 决定）。"
                )
            },
            "schedule_type": {
                "type": "string",
                "enum": ["cron", "interval", "once"],
                "description": "调度类型 (用于 create 操作): cron(cron表达式), interval(固定间隔秒数), once(一次性)"
            },
            "schedule_value": {
                "type": "string",
                "description": "调度值: cron表达式/间隔秒数/时间(+5s,+10m,+1h或ISO格式)"
            },
            "silent": {
                "type": "boolean",
                "default": False,
                "description": "Silent mode (default false): when true, the task runs normally but its result is not pushed. Set true only when the user explicitly says they don't need the result; reminder, notification and broadcast tasks must keep it false"
            },
            "notification_route": {"type": "object", "description": "显式通知路由；primary 包含 channel_type 和已授权 receiver；backup_enabled 默认 false，启用时必须提供 backup。"},
            "enabled": {"type": "boolean"},
            "content": {"type": "string", "description": "更新固定消息内容"},
        },
        "required": ["action"]
    }
    
    def __init__(self, config: dict = None):
        super().__init__()
        self.config = config or {}
        
        # Will be set by agent bridge
        self.task_store = None
        self.current_context = None
    
    def execute(self, params: dict) -> ToolResult:
        """
        Execute scheduler operations
        
        Args:
            params: Dictionary containing:
                - action: Operation type (create/list/get/delete/enable/disable)
                - Other parameters depending on action
            
        Returns:
            ToolResult object
        """
        # Extract parameters
        action = params.get("action")
        kwargs = params
        
        if not self.task_store:
            return ToolResult.fail("错误: 定时任务系统未初始化")
        
        try:
            if action == "create":
                result = self._create_task(**kwargs)
                return ToolResult.success(result)
            elif action == "list":
                result = self._list_tasks(**kwargs)
                return ToolResult.success(result)
            elif action == "get":
                result = self._get_task(**kwargs)
                return ToolResult.success(result)
            elif action == "destinations":
                from application import Application
                from common.runtime_identity import current_identity
                return ToolResult.success(json.dumps(Application.scheduler(self.task_store).destinations(
                    current_identity().agent_id), ensure_ascii=False))
            elif action == "update":
                return ToolResult.success(self._update_task(**kwargs))
            elif action == "delete":
                result = self._delete_task(**kwargs)
                return ToolResult.success(result)
            elif action == "enable":
                result = self._enable_task(**kwargs)
                return ToolResult.success(result)
            elif action == "disable":
                result = self._disable_task(**kwargs)
                return ToolResult.success(result)
            else:
                return ToolResult.fail(f"未知操作: {action}")
        except Exception as e:
            logger.error(f"[SchedulerTool] Error: {e}")
            return ToolResult.fail(f"操作失败: {str(e)}")
    
    def _create_task(self, **kwargs) -> str:
        """Create a new scheduled task"""
        name = kwargs.get("name")
        message = kwargs.get("message")
        ai_task = kwargs.get("ai_task")
        schedule_type = kwargs.get("schedule_type")
        schedule_value = kwargs.get("schedule_value")
        
        # Validate required fields
        if not name:
            raise ValueError("缺少任务名称 (name)")
        
        # Check that exactly one of message/ai_task is provided
        if not message and not ai_task:
            raise ValueError("必须提供 message（固定消息）或 ai_task（AI任务）之一")
        if message and ai_task:
            raise ValueError("message 和 ai_task 只能提供其中一个")
        
        if not schedule_type:
            raise ValueError("缺少调度类型 (schedule_type)")
        if not schedule_value:
            raise ValueError("缺少调度值 (schedule_value)")
        
        # Validate schedule
        schedule = self._parse_schedule(schedule_type, schedule_value)
        if not schedule:
            raise ValueError(f"无效的调度配置 - type: {schedule_type}, value: {schedule_value}")
        
        # Get context info for receiver
        if not self.current_context:
            raise ValueError("无法获取当前对话上下文")
        
        context = self.current_context
        
        # Create task
        task_id = str(uuid.uuid4())[:8]
        
        # Capture the real chat session_id at task creation time so that scheduler
        # can later inject the delivered output into the user's actual conversation
        # (in group chats, session_id != receiver, e.g. "user_id:group_id" on feishu).
        notify_session_id = context.get("session_id")

        # Build action based on message or ai_task
        if message:
            action = {
                "type": "send_message",
                "content": message,
                "receiver": context.get("receiver"),
                "receiver_name": self._get_receiver_name(context),
                "is_group": context.get("isgroup", False),
                "channel_type": self.config.get("channel_type", "unknown"),
                "notify_session_id": notify_session_id,
                "execution_session_id": notify_session_id,
            }
        else:  # ai_task
            action = {
                "type": "agent_task",
                "task_description": ai_task,
                "receiver": context.get("receiver"),
                "receiver_name": self._get_receiver_name(context),
                "is_group": context.get("isgroup", False),
                "channel_type": self.config.get("channel_type", "unknown"),
                "notify_session_id": notify_session_id,
                "execution_session_id": notify_session_id,
            }
            # silent only applies to ai_task; fixed messages always deliver
            if kwargs.get("silent", False):
                action["silent"] = True
        
        # 针对钉钉单聊，额外存储 sender_staff_id
        msg = context.kwargs.get("msg")
        if msg and hasattr(msg, 'sender_staff_id') and not context.get("isgroup", False):
            action["dingtalk_sender_staff_id"] = msg.sender_staff_id

        # A task created by the Agent in a desktop chat belongs to that chat
        # by default. Freeze its current project scope at creation time.
        if action["channel_type"] == "web":
            if not notify_session_id:
                raise ValueError("桌面定时任务需要当前对话")
            from agent.scheduler.conversation import validate_conversation_action
            action["conversation_mode"] = "source"
            action["source_session_id"] = notify_session_id
            try:
                action = validate_conversation_action(action, allow_pending_source=True)
            except ValueError as exc:
                raise ValueError(f"无法绑定当前对话: {exc}") from exc
        
        task_data = {
            "id": task_id,
            "name": name,
            "enabled": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "schedule": schedule,
            "action": action
        }
        from common.runtime_identity import current_identity
        identity = current_identity()
        task_data["owner_agent_id"] = identity.agent_id
        task_data["owner_user_id"] = identity.user_id
        
        # Calculate initial next_run_at
        next_run = self._calculate_next_run(task_data)
        if next_run:
            task_data["next_run_at"] = next_run.isoformat()
        
        # Save task
        from application import Application
        from common.runtime_identity import current_identity
        task_data = Application.scheduler(self.task_store).create(
            task_data, notification_route=kwargs.get("notification_route"), agent_id=current_identity().agent_id)
        
        # Format response
        schedule_desc = self._format_schedule_description(schedule)
        receiver_desc = task_data["action"]["receiver_name"] or task_data["action"]["receiver"]
        
        if message:
            content_desc = f"💬 固定消息: {message}"
        else:
            content_desc = f"🤖 AI任务: {ai_task}"

        # Warn the user at creation time so a mistaken silent flag is easy to spot
        silent_desc = "\n🔇 静默模式: 执行后不会推送结果" if action.get("silent") else ""

        return (
            f"✅ 定时任务创建成功\n\n"
            f"📋 任务ID: {task_id}\n"
            f"📝 名称: {name}\n"
            f"⏰ 调度: {schedule_desc}\n"
            f"👤 接收者: {receiver_desc}\n"
            f"{content_desc}{silent_desc}\n"
            f"🕐 下次执行: {next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else '未知'}"
        )

    def _update_task(self, **kwargs) -> str:
        task_id = kwargs.get("task_id")
        if not task_id:
            raise ValueError("缺少任务ID (task_id)")
        patch = {}
        if "name" in kwargs:
            patch["name"] = kwargs["name"]
        if "enabled" in kwargs:
            patch["enabled"] = kwargs["enabled"]
        if "notification_route" in kwargs:
            patch["notification_route"] = kwargs["notification_route"]
        if "content" in kwargs:
            patch["action"] = {"content": kwargs["content"]}
        if not patch:
            raise ValueError("没有要修改的定时任务字段")
        from application import Application
        from common.runtime_identity import current_identity
        task = Application.scheduler(self.task_store).update(task_id, patch, agent_id=current_identity().agent_id)
        return json.dumps({"task": task}, ensure_ascii=False)
    
    def _list_tasks(self, **kwargs) -> str:
        """List all tasks"""
        from application import Application
        tasks = Application.scheduler(self.task_store).list()
        
        if not tasks:
            return "📋 暂无定时任务"
        
        lines = [f"📋 定时任务列表 (共 {len(tasks)} 个)\n"]
        
        for task in tasks:
            status = "✅" if task.get("enabled", True) else "❌"
            schedule_desc = self._format_schedule_description(task.get("schedule", {}))
            next_run = task.get("next_run_at")
            next_run_str = datetime.fromisoformat(next_run).strftime('%m-%d %H:%M') if next_run else "未知"
            
            lines.append(
                f"{status} [{task['id']}] {task['name']}\n"
                f"   ⏰ {schedule_desc} | 下次: {next_run_str}"
            )
        
        return "\n".join(lines)
    
    def _get_task(self, **kwargs) -> str:
        """Get task details"""
        task_id = kwargs.get("task_id")
        if not task_id:
            raise ValueError("缺少任务ID (task_id)")
        from application import Application
        task = Application.scheduler(self.task_store).get(task_id)
        
        status = "启用" if task.get("enabled", True) else "禁用"
        schedule_desc = self._format_schedule_description(task.get("schedule", {}))
        action = task.get("action", {})
        next_run = task.get("next_run_at")
        next_run_str = datetime.fromisoformat(next_run).strftime('%Y-%m-%d %H:%M:%S') if next_run else "未知"
        last_run = task.get("last_run_at")
        last_run_str = datetime.fromisoformat(last_run).strftime('%Y-%m-%d %H:%M:%S') if last_run else "从未执行"
        
        return (
            f"📋 任务详情\n\n"
            f"ID: {task['id']}\n"
            f"名称: {task['name']}\n"
            f"状态: {status}\n"
            f"调度: {schedule_desc}\n"
            f"接收者: {action.get('receiver_name', action.get('receiver'))}\n"
            f"通知路由: {json.dumps(task.get('notification_route'), ensure_ascii=False)}\n"
            f"消息: {action.get('content')}\n"
            f"下次执行: {next_run_str}\n"
            f"上次执行: {last_run_str}\n"
            f"创建时间: {datetime.fromisoformat(task['created_at']).strftime('%Y-%m-%d %H:%M:%S')}"
        )
    
    def _delete_task(self, **kwargs) -> str:
        """Delete a task"""
        task_id = kwargs.get("task_id")
        if not task_id:
            raise ValueError("缺少任务ID (task_id)")
        from application import Application
        task = Application.scheduler(self.task_store).delete(task_id)
        return f"✅ 任务 '{task['name']}' ({task_id}) 已删除"
    
    def _enable_task(self, **kwargs) -> str:
        """Enable a task"""
        task_id = kwargs.get("task_id")
        if not task_id:
            raise ValueError("缺少任务ID (task_id)")
        from application import Application
        task = Application.scheduler(self.task_store).enable(task_id, True)
        return f"✅ 任务 '{task['name']}' ({task_id}) 已启用"
    
    def _disable_task(self, **kwargs) -> str:
        """Disable a task"""
        task_id = kwargs.get("task_id")
        if not task_id:
            raise ValueError("缺少任务ID (task_id)")
        from application import Application
        task = Application.scheduler(self.task_store).enable(task_id, False)
        return f"✅ 任务 '{task['name']}' ({task_id}) 已禁用"
    
    def _parse_schedule(self, schedule_type: str, schedule_value: str) -> Optional[dict]:
        """Parse and validate schedule configuration"""
        try:
            if schedule_type == "cron":
                # Validate cron expression
                iter_cron(schedule_value)
                return {"type": "cron", "expression": schedule_value}
            
            elif schedule_type == "interval":
                # Parse interval in seconds
                seconds = int(schedule_value)
                if seconds <= 0:
                    return None
                return {"type": "interval", "seconds": seconds}
            
            elif schedule_type == "once":
                # Parse datetime - support both relative and absolute time
                
                # Check if it's relative time (e.g., "+5s", "+10m", "+1h", "+1d")
                if schedule_value.startswith("+"):
                    import re
                    match = re.match(r'\+(\d+)([smhd])', schedule_value)
                    if match:
                        amount = int(match.group(1))
                        unit = match.group(2)
                        
                        from datetime import timedelta
                        now = datetime.now()
                        
                        if unit == 's':  # seconds
                            target_time = now + timedelta(seconds=amount)
                        elif unit == 'm':  # minutes
                            target_time = now + timedelta(minutes=amount)
                        elif unit == 'h':  # hours
                            target_time = now + timedelta(hours=amount)
                        elif unit == 'd':  # days
                            target_time = now + timedelta(days=amount)
                        else:
                            return None
                        
                        return {"type": "once", "run_at": target_time.isoformat()}
                    else:
                        logger.error(f"[SchedulerTool] Invalid relative time format: {schedule_value}")
                        return None
                else:
                    # Absolute ISO time. Normalize to tz-naive local so it
                    # stays comparable with the scheduler's datetime.now().
                    parsed = datetime.fromisoformat(schedule_value)
                    if parsed.tzinfo is not None:
                        parsed = parsed.astimezone().replace(tzinfo=None)
                    return {"type": "once", "run_at": parsed.isoformat()}
            
        except Exception as e:
            logger.error(f"[SchedulerTool] Invalid schedule: {e}")
            return None
        
        return None
    
    def _calculate_next_run(self, task: dict) -> Optional[datetime]:
        """Calculate next run time for a task"""
        schedule = task.get("schedule", {})
        schedule_type = schedule.get("type")
        now = datetime.now()
        
        if schedule_type == "cron":
            expression = schedule.get("expression")
            cron = iter_cron(expression, now)
            return cron.get_next(datetime)
        
        elif schedule_type == "interval":
            seconds = schedule.get("seconds", 0)
            from datetime import timedelta
            return now + timedelta(seconds=seconds)
        
        elif schedule_type == "once":
            run_at_str = schedule.get("run_at")
            return datetime.fromisoformat(run_at_str)
        
        return None
    
    def _format_schedule_description(self, schedule: dict) -> str:
        """Format schedule as human-readable description"""
        schedule_type = schedule.get("type")
        
        if schedule_type == "cron":
            expr = schedule.get("expression", "")
            # Try to provide friendly description
            if expr == "0 9 * * *":
                return "每天 9:00"
            elif expr == "0 */1 * * *":
                return "每小时"
            elif expr == "*/30 * * * *":
                return "每30分钟"
            else:
                return f"Cron: {expr}"
        
        elif schedule_type == "interval":
            seconds = schedule.get("seconds", 0)
            if seconds >= 86400:
                days = seconds // 86400
                return f"每 {days} 天"
            elif seconds >= 3600:
                hours = seconds // 3600
                return f"每 {hours} 小时"
            elif seconds >= 60:
                minutes = seconds // 60
                return f"每 {minutes} 分钟"
            else:
                return f"每 {seconds} 秒"
        
        elif schedule_type == "once":
            run_at = schedule.get("run_at", "")
            try:
                dt = datetime.fromisoformat(run_at)
                return f"一次性 ({dt.strftime('%Y-%m-%d %H:%M')})"
            except Exception:
                return "一次性"
        
        return "未知"
    
    def _get_receiver_name(self, context: Context) -> str:
        """Get receiver name from context"""
        try:
            msg = context.get("msg")
            if msg:
                if context.get("isgroup"):
                    return msg.other_user_nickname or "群聊"
                else:
                    return msg.from_user_nickname or "用户"
        except Exception:
            pass
        return "未知"
