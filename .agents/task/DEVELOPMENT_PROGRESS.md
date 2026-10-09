# Stella 开发进度

更新时间：2026-10-09。依据当前专用分支 `feat/apple-calendar-eventkit-20261009` 的代码、提交与隔离测试记录；未运行的真机和外部服务场景不计为完成。

| 阶段 | 状态 | 已核对的成果 | 下一步 |
| --- | --- | --- | --- |
| 0 现状与依赖 | 完成 | 从 `develop` 建立的专用分支已有 Apple Calendar 四个提交；恢复了未提交的同步安全回归。通知共用 `agent/scheduler/delivery.py`，事务提醒由 `TodoService` 和 `scheduler_link` 维护，定时任务由 `SchedulerService` 管理；Apple Calendar 已有 EventKit 桥接和 `AppleCalendarSync`，Reminders 尚无对应适配。Work 已有 `WorkspaceService`，安全已有 `SecurityGateway`、`SecurityPolicy`、`ProcessSandbox`，均需按阶段验收。 | 按已有边界复用服务，避免重复实现。 |
| 1 定时任务两个 Bug | 本地验收通过 | 提交 `27e055a4`：卡片和关联入口分开；失效关联显示详情提示；运行时微信通道定位、目录状态、定时就绪检查和发送均使用实际实例。Python、浏览器及增量门禁通过。 | 真实微信发送需授权测试会话。 |
| 2 通知与可靠投递 | 本地验收通过 | 提交 `bf2ada15`、`78acf283`、`da0f4674`、`9a70a17a` 及本阶段 UI 提交：事务与独立任务共用显式首选/备用路由验证；Agent 和 UI 经同一服务创建、查询、修改；备用默认关闭，完成的任务输出缓存并与投递状态分开；平台响应、等待恢复、未知、过期和限次重试均有记录；编辑器可刷新状态、查看最近投递并测试发送。 | 真实飞书/微信发送仍需隔离测试目标和有效会话；阶段 3 继续 Apple Reminders。 |
| 3 Apple EventKit 与同步 | Calendar 部分完成 | 四个既有提交实现 Calendar 桥接、双向对账、桌面入口；提交 `27e055a4` 经代码复核补齐空扫描及滚动窗口保护、本地删除确认、重复事件标识匹配和重复规则清除。31 项相关测试及 Swift helper 编译通过。 | 完成真机隔离日历验收、Reminders 独立同步及 Apple Agent 工具。 |
| 4 Apple 设置与页面 Agent | 待实现 | 当前 Apple Calendar 使用日程页弹窗；尚无统一 Apple 设置中心及日程/事务内嵌 Agent。 | 在阶段 2/3 接口稳定后实施。 |
| 5 Work 工作区 | 待核实 | 已定位 `agent/workspace/service.py` 和项目目录能力，未完成隔离验收。 | 核对会话/任务目录与权限边界。 |
| 6 安全权限 | 待核实 | 已定位权限策略、网关和进程沙箱，未完成四模式与 Custom 验收。 | 依赖阶段 5 的统一工作区上下文。 |

## 本轮验证

- PASS：`tests/test_apple_calendar_sync.py`（30 项）、Swift 事件标识测试、Apple 桌面 API 确认测试；微信就绪和发送测试均经 RED→GREEN。
- PASS：`tests/ui_tasks.py`（模拟桌面后端的任务详情、关联入口、失效关联和微信选项交互）。
- PASS：`desktop` TypeScript 检查、Swift EventKit helper 编译；Apple Calendar 浏览器回归覆盖 Stella 本地删除确认。
- PASS：`tests/ui_notification_routes.py`：定时任务和事务提醒的首选、备用默认关闭与显式开关、仅飞书、微信无接收人和刷新、状态显示、测试发送；模拟后端隔离运行。
- PASS：`.venv/bin/python scripts/quality_check.py incremental`；Ruff、1401 项 pytest（4 项 SKIP）、ESLint、构建、类型检查、Node 测试及 UI 检查通过。阶段 2 最后修复测试发送仅验证首选路由后，相关回归测试亦通过。
- SKIP：真实 Apple 授权日历、微信/飞书外部发送、打包运行；未使用用户账号或数据。

## 下一步

1. 完成阶段 2 分支审查并处理重要发现；在隔离测试账号可用时补真实渠道验收。
2. 继续阶段 3 的 Reminders 独立同步和 Apple Agent 接口，随后推进统一设置、页面 Agent、Work、安全权限。
