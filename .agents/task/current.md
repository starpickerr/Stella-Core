# 当前任务现状与决策记录

本文保存需求依据和 2026-10-10 的代码核查结果。[需求与验收](requirements.md) 是开发和验收的依据；本记录中的现状描述不表示功能已实现，待定扩展项也不应被实现为默认行为。

## 渠道决策摘要

- 发送选择器限定为已连接的电脑客户端、Telegram Bot 和企业微信智能机器人；目标还须具备接收条件，不要求近期再次向 Stella 发消息。
- “客户端”指电脑操作系统通知横幅或通知中心条目，不指聊天对话或 App 内提示；手机不在本轮范围。企业微信智能机器人特指 WebSocket 长连接模式。
- 定时任务和待办提醒不再设置备用渠道；一次发送只有一个渠道和目标，失败后不自动改投。平台支持主动推送不等于 Stella 当前已实现。

## 现有功能线索

- 定时任务编辑器 `desktop/src/renderer/src/pages/TasksPage.tsx` 和待办提醒编辑器 `desktop/src/renderer/src/pages/TodosPage.tsx` 均有备用渠道开关及接收人字段。
- `agent/scheduler/delivery.py` 的 `normalize_notification_route` 使用 `backup_enabled`、`backup`；`agent/scheduler/dispatch.py` 在首选投递失败后可能尝试备用目标。定时任务和待办 Agent 工具描述也暴露了备用配置。
- 这些位置用于开发时定位清理范围，不表示本轮已修改代码。旧数据处理和验收以 [需求与验收](requirements.md#3-移除现有备用渠道) 为准。

## 官方资料依据

- [Telegram 官方机器人说明](https://core.telegram.org/bots)：机器人不能率先与陌生用户开始对话；用户先发消息或将机器人加入群后，可在已建立的聊天中发送。[Bot FAQ](https://core.telegram.org/bots/faq) 说明机器人向用户广播消息的限速规则。[Bot token 教程](https://core.telegram.org/bots/tutorial) 说明 token 可以由管理员撤销。
- [企业微信智能机器人官方 Node.js SDK](https://github.com/WecomTeam/aibot-node-sdk)：文档明确写有向指定会话主动推送、无需依赖回调帧；使用 `botId + secret` 认证，并维护长连接心跳和断线重连。
- 客户端是 Stella 自身的通知目标，不由外部平台文档定义；需在已登录且允许通知的电脑客户端上显示操作系统通知横幅或通知中心条目，而不是依赖打开对话或新建应用内消息页。
- [腾讯 QQ 机器人发送文档](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md) 明确写明主动推送能力自 2025-04-21 起不再提供。[腾讯微信渠道协议说明](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md) 明确指出缺少 `context_token` 时客户端仍尝试发送，不等于服务端接受。二者均不纳入本轮主动发送选择器。

## 尚未确定的后续扩展

- 客户端系统通知的点击去向与可配置文案模板。通知权限关闭时本轮仍须给出明确的不可用状态和发送失败原因，不能因为这项体验细节未定而静默成功。
- 除本轮已涉及的定时任务、待办提醒及明确发起的发送操作外，其他 Stella 事件是否也可触发主动发送，以及对应的消息模板和内容类型。
- 多渠道或多接收对象发送属于将来扩展；**本轮已确定单次发送只能选择一个渠道和一个接收目标，且没有备用目标**。

这些扩展尚未确认，不应被开发 Agent 当作已批准的本轮功能。

## 设置整理：代码线索

- `desktop/src/renderer/src/pages/BriefingPage.tsx` 目前在页面内切换 `SettingsPanel`，其中包含邮箱、eLearning、动作授权和筛选规则。统一设置页迁移范围以 [第 5 节](requirements.md#5-设置入口整理) 为准。
- `desktop/src/renderer/src/layout/NavRail.tsx` 底部目前由版本号和“更多”菜单组成；菜单含主题、语言、检查更新、日志、文档、项目网站和反馈等。日志另有侧边栏入口。
- 日程与待办页面目前有前往 Apple 集成设置的链接；增加返回原页面的行为时应覆盖这两个已有入口。

## 能力页面：代码线索

- 页面命名与目录验收见 [需求与验收](requirements.md#6-进化页面更新为能力)。
- 当前侧边栏 `/skills` 的中文标签是“进化”，英文是“Evolution”；页面标题另为“技能管理”／“Skills”。页面同时展示“内置工具”和“技能”，两处名称需要一起统一。
- 当前 `SkillsPage.tsx` 通过 `apiClient.getTools()` 读取 `/api/tools`。`agent/tools/__init__.py` 的 `__all__` 列有 24 个内置工具类候选（已排除 `BaseTool`、`ToolManager` 和外部 `McpTool`）；`ToolsHandler` 却只遍历 `ToolManager.tool_classes`。`ToolManager` 在加载时明确跳过 `MemorySearchTool` 和 `MemoryGetTool`，而 `bridge/agent_initializer.py` 会在运行时单独构造并注入 `memory_search` 和 `memory_get`。因此当前页面**未包含所有实际内置工具**，至少漏了这两项。
- `ToolManager` 还可能因可选依赖缺失而不加载某些内置工具；Agent 初始化也会按配置跳过某些工具。当前页面没有区分“属于内置目录”和“此时可用”。页面并发请求工具与技能，任一请求失败只写控制台日志，已有空列表会被当作“暂无”显示。以上是需求中的目录与错误状态需要修正的原因，不表示已改动代码。
- 现有两类卡片都使用 `line-clamp-2`，长介绍会被省略号截断。`ToolInfo` 当前只有 `name`、`description` 两个字符串；`/api/tools` 取 `instance.description`，仅对定时任务有英文特例，且请求没有传入前端 `getLang()`。各工具的 `description` 有中文、英文和面向 Agent 的操作指令，不能直接满足双语用户文案。详见 [能力页面实施参考](capabilities.md)。

## 桌面端界面统一：已确认范围

- 用户指出各页面顶部横线有的缺失、有的只在中间、有的贯穿两边，页面主体有的居中限宽、有的铺满。讨论中曾选择“全部铺满可用宽度”，随后用定时任务卡片截图明确修正：**只有页面标题区域和页面级横线需要横贯主内容区；下方内容可按需要居中、限宽、分栏或铺满**。截图是布局示例，不是让卡片数据或文案成为需求。
- 页面级要求见 [需求与验收](requirements.md#7-桌面端页面顶部与内容布局统一)，逐页代码线索见 [界面统一实施参考](ui-consistency.md)。本轮只记录需求，尚未修改界面代码。
