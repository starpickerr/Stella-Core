# Stella 开发进度

更新时间：2026-10-10。依据当前专用分支 `feat/apple-calendar-eventkit-20261009` 的代码、提交与隔离测试记录；未运行的真机和外部服务场景不计为完成。

| 阶段 | 状态 | 已核对的成果 | 下一步 |
| --- | --- | --- | --- |
| 0 现状与依赖 | 完成 | 从 `develop` 建立的专用分支已有 Apple Calendar 四个提交；恢复了未提交的同步安全回归。通知共用 `agent/scheduler/delivery.py`，事务提醒由 `TodoService` 和 `scheduler_link` 维护，定时任务由 `SchedulerService` 管理；Apple Calendar 已有 EventKit 桥接和 `AppleCalendarSync`，Reminders 尚无对应适配。Work 已有 `WorkspaceService`，安全已有 `SecurityGateway`、`SecurityPolicy`、`ProcessSandbox`，均需按阶段验收。 | 按已有边界复用服务，避免重复实现。 |
| 1 定时任务两个 Bug | 本地验收通过 | 提交 `27e055a4`：卡片和关联入口分开；失效关联显示详情提示；运行时微信通道定位、目录状态、定时就绪检查和发送均使用实际实例。Python、浏览器及增量门禁通过。 | 真实微信发送需授权测试会话。 |
| 2 通知与可靠投递 | 本地验收通过 | 提交 `bf2ada15`、`78acf283`、`da0f4674`、`9a70a17a`、`e69ac4a6` 及审查修复：事务与独立任务共用显式首选/备用路由验证；Agent 和 UI 经同一服务创建、查询、修改；备用默认关闭，完成的任务输出缓存并与投递状态分开；平台响应、等待恢复、未知、过期和限次重试均有记录；编辑器可刷新状态、查看最近投递并测试发送。审查后补齐失效渠道下的普通编辑、Web 运行时会话目标和连接不确定/微信分块发送去重。 | 真实飞书/微信发送仍需隔离测试目标和有效会话；阶段 3 继续 Apple Reminders。 |
| 3 Apple EventKit 与同步 | 本地验收通过 | 独立 Calendar/Reminders 授权、原生桥接、映射与双向对账；桌面与 Agent 共用 Application 管理器。一次性操作须选定来源及条目、预览并确认；首次持续同步须预览并确认。独立复核后修复失败扫描确认删除、父事务级联删除、相对闹钟覆盖、原生写入后映射恢复及 Agent 写入权限分级。假 EventKit、Swift 编译和浏览器交互通过。 | 在隔离测试日历/列表和打包应用中验收真实 Apple 授权；阶段 4 实现统一设置和页面 Agent。 |
| 4 Apple 设置与页面 Agent | 本地验收通过 | Apple 日历与提醒事项统一在设置中心，分别控制自动同步、来源、方向、预览、一次性传输、冲突和断开；日程与事务页面使用独立可恢复的内嵌 Agent 会话与草稿，快捷菜单直接发送并进入同一设置中心。修复 Agent 配置绕过自动同步开关、历史加载覆盖新消息、忙碌时改动一次性传输条件、快捷请求离页丢失及本地时区日期偏移。事务主体未改造。 | 真实 Apple 授权及打包运行仍需隔离测试目标；继续阶段 5。 |
| 5 Work 工作区 | 本地验收通过 | 提交 `8fc7c22c`、`5d7370f8`、`109810b9`、`0b73a764`：会话/项目/自动化上下文、精确文件共享、网关与 OS 沙箱私有边界。Python 工作区测试 54 项通过；增量门禁含 `tests/ui_work_shares.py`。 | 独立审查 Work 范围后进入阶段 6。 |
| 6 安全权限 | 本地验收通过 | 产品预设 `read-only`/`workspace-write`/`full-access`/`custom`；`approval` 迁为 Custom 快照、`project-full` 等同工作区写入；持久化策略不被 Agent mode 放宽；Full Access 仍报告沙箱 enabled；extra_roots 不能指向私有 Work。增量门禁通过。 | 独立审查后合并 `develop`。 |

## 本轮验证

- PASS：`tests/test_apple_calendar_sync.py`（30 项）、Swift 事件标识测试、Apple 桌面 API 确认测试；微信就绪和发送测试均经 RED→GREEN。
- PASS：`tests/ui_tasks.py`（模拟桌面后端的任务详情、关联入口、失效关联和微信选项交互）。
- PASS：`desktop` TypeScript 检查、Swift EventKit helper 编译；Apple Calendar 浏览器回归覆盖 Stella 本地删除确认。
- PASS：`tests/ui_notification_routes.py`：定时任务和事务提醒的首选、备用默认关闭与显式开关、仅飞书、微信无接收人和刷新、状态显示、测试发送；模拟后端隔离运行。
- PASS：`.venv/bin/python scripts/quality_check.py incremental`；Ruff、1445 项 pytest（4 项 SKIP）、ESLint、构建、类型检查、Node 测试及 UI 检查通过。阶段 2 独立审查的三项重要发现均有先失败、后通过的回归测试。
- PASS：阶段 3 假 EventKit 同步/API/Agent/权限回归 71 项；Swift EventKit helper 编译及无真实 Reminder store 的闹钟测试通过。浏览器日历设置的首次预览、确认、同步、冲突及断开流程通过。
- PASS：阶段 4 Apple 设置与内嵌 Agent 浏览器交互：独立开关、精确条目预览/确认、离页恢复、审批、连续快捷请求与页面刷新；Agent 自动同步开关回归先失败后通过，设置忙碌状态和历史加载用例先失败后通过。分支复核发现并处理上述竞态；独立审查代理中途达到额度限制，未产生完整审查结论。
- PASS：阶段 5 Work Python 测试 54 项（context/runtime/shares/boundaries/sandbox/browser/scheduler/project）。
- PASS：`.venv/bin/python scripts/quality_check.py incremental`（本次会话，阶段 6 后）：Ruff；pytest 1489 passed / 4 skipped；ESLint、构建、类型检查、Node；UI 含 Work 共享与安全四模式/完全访问提示。`policy` SKIP。
- SKIP：真实 Apple 日历与提醒事项授权/读写、微信/飞书外部发送、打包运行；未使用用户账号或数据。Windows 进程沙箱本机不适用。

## 下一步

1. 在隔离测试账号可用时补真实渠道与 Apple 授权验收。
2. 完成 Work 与安全权限独立审查后，按既有授权合并本地 `develop`。
