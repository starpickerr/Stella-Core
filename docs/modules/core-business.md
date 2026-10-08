# 核心业务模块代码地图

| 领域 | 当前主实现 | 关键测试和说明 |
| --- | --- | --- |
| 事务 | `agent/todos/service.py` 管理状态、层级、依赖、提醒；`agent/tools/todos/` 暴露 Agent 调用 | `tests/test_todos.py`；[事务模块说明](../../agent/todos/README.md) |
| 日程 | `agent/calendar/service.py` 管理事件、分类与简报交接 | `tests/test_calendar.py`；[日程模块说明](../../agent/calendar/README.md) |
| 账单 | `agent/bills/service.py`、`store.py`、`schema.sql` 管理账本与期间报表 | `tests/test_bill_service.py`, `tests/test_bill_store.py` |
| 简报 | `agent/briefing/pipeline.py` 获取来源，`generator.py` 调用 Agent，`store.py` 保存快照，`actions.py` 处理业务回执 | `tests/test_briefing_*.py`, `tests/ui_briefing.py`；[简报说明](../../agent/briefing/README.md) |
| 自动化/定时 | `agent/scheduler/service.py` 领取任务，`integration.py` 绑定 Agent/用户身份并分派动作 | `tests/test_scheduler_*.py` |

各领域使用 `Application.port`/`Application.command` 作为共享调用边界；数据库路径由 `common/state_dir.py` 解析。每次跨模块变更须检查 Agent 工具、HTTP、桌面和调度的调用是否仍一致。
