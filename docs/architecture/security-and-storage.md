# 数据库与权限边界

`common/runtime_identity.py` 维护运行身份，`common/state_dir.py` 根据身份解析各类状态路径。当前业务库包括用户级 `todos/todos.db`、`calendar/calendar.db`、`bills/bills.db`、`briefing/briefing.db`；会话和调度还有各自存储。测试可通过显式服务路径和临时 `HOME`/`STELLA_DATA_DIR` 隔离。不要用真实用户目录运行审计或 Evals。

| 模块 | 表/模型入口 | 迁移和恢复关注点 |
| --- | --- | --- |
| 事务 | 外仓插件 `stella.tasks`（`backend/domain/schema.sql`）中的 `todos`、依赖、提醒和墓碑表 | 旧日程事务迁移、幂等应用、用户编辑保护 |
| 日程 | `agent/calendar/service.py` 中的事件、分类和交接表 | 简报来源变更与已有事件冲突 |
| 账单 | 外仓插件 `stella.bills`（`backend/domain/schema.sql`、`store.py`） | 账本、计划付款、期间报表一致性 |
| 简报 | `agent/briefing/schema.sql`、`actions.sql`、`store.py` | 候选快照、版本、来源游标、行动回执与 outbox |
| 会话 | `agent/memory/conversation_store.py` | 旧库迁移、运行准入与消息顺序 |

权限模式与平台边界已有 [详细说明](../security-permission-modes.md)。运行时的可信判定点是 `agent/runtime/tool_invocation.py` 和 `agent/permission/gateway.py`；`Application.command` 对定时业务写入再次校验。Web/API 端还需验证认证，不能把前端隐藏按钮当作授权。涉及外部资源的工具要检查路径、URL、重定向与凭证泄露。权限和事务的失败恢复必须有隔离测试。
