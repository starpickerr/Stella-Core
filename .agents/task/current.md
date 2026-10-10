# 当前任务讨论记录：主动发送消息

## 已确认

- Stella 目前缺少统一的主动发送能力。本轮目标包括向客户端发系统通知，以及向选定的外部渠道主动发消息；不依赖收件人近期先向 Stella 发消息。
- 主动发送的渠道选择器只允许“客户端、Telegram Bot、企业微信智能机器人”三个选项。三者都必须有可用的实际发送能力。
- 用户提供的截图是操作系统通知横幅，含应用图标、标题、正文和系统显示的时间。“客户端”应按这种系统通知实现，而不是单独的 App 内消息页、应用内弹窗或对话消息。用户随后限定本轮只考虑 Stella 电脑客户端，手机通知不在本轮范围内。
- 这里的企业微信智能机器人是 WebSocket 长连接接入方式，不泛指企业微信的其他机器人或应用接口。
- 用户确认不再保留项目原有的备用渠道功能。定时任务和待办提醒都应只用一个选定目标，失败时不自动改投备用目标。
- 用户补充：三个主动发送渠道必须先在 Stella 中完成连接，目标也要已经建立可发送关系；未连接时不能直接发送。建立连接后不要求收件人近期再次发消息。
- 平台本身允许主动发送，不代表 Stella 当前已经实现；需求以 [需求与验收](requirements.md) 为准。

## 现有功能线索

- 定时任务编辑器 `desktop/src/renderer/src/pages/TasksPage.tsx` 和待办提醒编辑器 `desktop/src/renderer/src/pages/TodosPage.tsx` 均有备用渠道开关及接收人字段。
- `agent/scheduler/delivery.py` 的 `normalize_notification_route` 使用 `backup_enabled`、`backup`；`agent/scheduler/dispatch.py` 在首选投递失败后可能尝试备用目标。定时任务和待办 Agent 工具描述也暴露了备用配置。
- 这些位置用于开发时定位清理范围，不表示本轮已修改代码。旧数据处理和验收以 [需求与验收](requirements.md#3-移除现有备用渠道) 为准。

## 官方资料依据

- [Telegram 官方机器人说明](https://core.telegram.org/bots)：机器人不能率先与陌生用户开始对话；用户先发消息或将机器人加入群后，可在已建立的聊天中发送。[Bot FAQ](https://core.telegram.org/bots/faq) 说明机器人向用户广播消息的限速规则。[Bot token 教程](https://core.telegram.org/bots/tutorial) 说明 token 可以由管理员撤销。
- [企业微信智能机器人官方 Node.js SDK](https://github.com/WecomTeam/aibot-node-sdk)：文档明确写有向指定会话主动推送、无需依赖回调帧；使用 `botId + secret` 认证，并维护长连接心跳和断线重连。
- 客户端是 Stella 自身的通知目标，不由外部平台文档定义；需在已登录且允许通知的电脑客户端上显示操作系统通知横幅或通知中心条目，而不是依赖打开对话或新建应用内消息页。
- [腾讯 QQ 机器人发送文档](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md) 明确写明主动推送能力自 2025-04-21 起不再提供。[腾讯微信渠道协议说明](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md) 明确指出缺少 `context_token` 时客户端仍尝试发送，不等于服务端接受。二者均不纳入本轮主动发送选择器。

## 仍待产品细化，不阻挡本轮渠道范围

- 提醒的文案、点击后的去向，以及用户关闭系统通知权限时的界面提示。
- 首批允许哪些 Stella 事件或任务触发主动发送、消息模板和内容类型。
- 一个任务是否可同时选择多个渠道或多个接收对象；在确定前按单次发送指定一个渠道和一个接收目标理解。

这些细节尚未确认，不应被开发 Agent 当作已批准的额外功能。
