# 数据流与模块接口

`application/api.py` 定义受限的领域方法集合和 `RequestContext`。桌面 HTTP 请求、Agent 工具、定时任务使用相同服务端口；`Application.command` 为调度写入提供命令名、权限检查和可选幂等键。`application/operations.py` 记录运行中业务操作的完成或结果未知状态，避免 Agent 在不确定失败后声称已成功。

| 场景 | 路径 | 关键边界 |
| --- | --- | --- |
| 桌面事务 | React → 本地 HTTP API → `Application.port('todos')` → `TodosPluginFacade` → `stella.tasks` 插件 → SQLite | Python 服务校验；UI 不直接写库 |
| Agent 业务工具 | 消息 → Bridge/执行器 → 权限网关 → Tool → `Application.port`/`command` → 领域服务 | 工具授权与业务校验分开 |
| 简报 | `BriefingPipeline` → 来源适配器 → Agent 逐项判断/报告 → `BriefingStore` → `BriefingActions`/事务与日程 | 来源游标在成功持久化后推进；行动有回执与幂等恢复 |
| 自动化 | `SchedulerService` 领取触发 → `scheduler.integration` 绑定身份 → Agent/Tool 或 `Application.command` | 发生记录、重试和通知交付分开 |

简报详情和事务跟踪见 [简报行动设计](../briefing-actions.md)。新增入口应调用现有服务，不复制领域校验。修改跨域写入要检查所有入口使用同一身份和错误语义。
