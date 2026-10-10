# 当前任务讨论记录：主动发送消息

## 已确认

- Stella 目前缺少主动向外部渠道发送消息的功能。本轮目标是新增 Stella 发起的出站消息，不依赖收件人近期先向 Stella 发消息。
- 主动发送的渠道选择器只允许“客户端、Telegram Bot、企业微信智能机器人”三个选项。三者都必须有可用的实际发送能力。
- 这里的企业微信智能机器人是 WebSocket 长连接接入方式，不泛指企业微信的其他机器人或应用接口。
- 平台本身允许主动发送，不代表 Stella 当前已经实现；需求以 [需求与验收](requirements.md) 为准。

## 官方资料依据

- [Telegram 官方机器人说明](https://core.telegram.org/bots)：机器人不能率先与陌生用户开始对话；用户先发消息或将机器人加入群后，可在已建立的聊天中发送。[Bot FAQ](https://core.telegram.org/bots/faq) 说明机器人向用户广播消息的限速规则。[Bot token 教程](https://core.telegram.org/bots/tutorial) 说明 token 可以由管理员撤销。
- [企业微信智能机器人官方 Node.js SDK](https://github.com/WecomTeam/aibot-node-sdk)：文档明确写有向指定会话主动推送、无需依赖回调帧；使用 `botId + secret` 认证，并维护长连接心跳和断线重连。
- 客户端是 Stella 自身的消息目标，不由外部平台文档定义；具体呈现和持久化方式须结合 Stella 现有客户端设计实现。
- [腾讯 QQ 机器人发送文档](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/send.md) 明确写明主动推送能力自 2025-04-21 起不再提供。[腾讯微信渠道协议说明](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md) 明确指出缺少 `context_token` 时客户端仍尝试发送，不等于服务端接受。二者均不纳入本轮主动发送选择器。

## 仍待产品细化，不阻挡本轮渠道范围

- 客户端消息的具体展示位置，以及客户端离线时是否需要系统推送。
- 首批允许哪些 Stella 事件或任务触发主动发送、消息模板和内容类型。
- 一个任务是否可同时选择多个渠道或多个接收对象；在确定前按单次发送指定一个渠道和一个接收目标理解。

这些细节尚未确认，不应被开发 Agent 当作已批准的额外功能。
