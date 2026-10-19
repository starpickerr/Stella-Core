# 核心业务模块代码地图

| 领域 | 当前主实现 | 关键测试和说明 |
| --- | --- | --- |
| 事务 | 外仓插件 `stella.tasks` 管理状态、层级、依赖、提醒；`core/services/todos_facade.py` 转发，`agent/tools/todos/` 暴露 Agent 调用 | `tests/test_todos.py`（Core 集成）、Stella-Plugins `plugins/tasks/tests`（领域）；[事务模块说明](../../agent/todos/README.md) |
| 日程 | `agent/calendar/service.py` 管理事件、分类与简报交接 | `tests/test_calendar.py`；[日程模块说明](../../agent/calendar/README.md) |
| 账单 | Stella-Plugins 的 `plugins/bills/backend/domain/` 独占账本、期间报表和 XLSX 导出；Core 的 `core/services/bills_facade.py` 通过 RPC 调用，未安装/停用时拒绝旧实现回退 | 外仓 `plugins/bills/tests/`；Core `tests/test_bills_facade_port.py`、`tests/test_bills_web.py` |
| 简报 | `agent/briefing/pipeline.py` 获取来源，`generator.py` 调用 Agent，`store.py` 保存快照，`actions.py` 处理业务回执 | `tests/test_briefing_*.py`, `tests/ui_briefing.py`；[简报说明](../../agent/briefing/README.md) |
| 自动化/定时 | `agent/scheduler/service.py` 领取任务，`integration.py` 绑定 Agent/用户身份并分派动作 | `tests/test_scheduler_*.py` |

各领域使用 `Application.port`/`Application.command` 作为共享调用边界；数据库路径由 `common/state_dir.py` 解析。每次跨模块变更须检查 Agent 工具、HTTP、桌面和调度的调用是否仍一致。
