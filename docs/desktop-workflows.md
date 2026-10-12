# Electron 桌面业务工作流

Stella 的桌面页面通过本机 Python API 操作业务库。事务、日程和账单按用户目录保存；自动化计划与 JobRun 按 Agent 保存。单 Agent 旧安装保持原路径，多 Agent 前需运行用户数据迁移。

## 事务与安全

事务可以设置计划处理日期（与截止日期分开）、清单、标签、旗标和检查项。焦点视图按今天、即将到期、旗标与清单筛选。重复事务的完成状态和检查项按 occurrence 日期隔离；编辑模板不会把别的实例标为完成。

安全页可修改全局工具权限，聊天里的会话权限覆盖全局设置。定时运行会在执行时读取来源会话的项目和权限；未绑定会话时使用 Agent workspace 和全局权限。修改密码需要重新认证。只读模式拒绝业务写工具与未分类的外部工具。`agent_tool_allowlist` 可限制工具名，`agent_account_allowlist` 可限制外部工具调用的 `account` 或 `account_id`；空列表表示不额外限制。

## 定时任务与投递

任务页支持 cron、interval（至少60秒）和 once，动作可以是固定消息或 Agent 任务。已有 tool_call、skill_call、application_command 和用户设置的简报动作的完整 action 元数据保留可读；修改名称、时间或开关不会丢弃工具参数。

选择已配置的客户端、飞书或微信渠道，再设置接收人。执行来源与投递目标独立：修改目标不会改动来源会话的模型、项目和权限。切换渠道会移除旧渠道的接收标识元数据。

- 客户端接收人是 conversation/session ID；目标会话轮询就绪后才投递。
- 飞书需要已配置并连接的应用、发送权限和接收人可访问范围。用户可使用 Open ID、User ID、Union ID 或邮箱；群聊使用 Chat ID。请匹配“接收方式”和真实标识。
- 微信接收人必须先向机器人发送消息，建立服务器提供的 context token。应用重启后可能需要重新建立会话。缺 token 会明示不能投递；发送被拒时查看渠道状态或重新登录。渠道协议的登录状态和 token 由服务器决定。

执行成功的完整结果先保存到用户 runs 目录，再投递。投递失败会保留原计划发生实例并只重试发送，不重跑已成功的模型或有副作用工具。明确执行失败或结果未知会停用任务，记录 failed/outcome_unknown；核对目标业务状态后再决定是否手动运行。手动运行生成独立 JobRun，不改变下一次计划时间。渠道缺少端到端幂等保证，超时后重发仍可能产生重复消息。

## 保存但未运行的聊天输入

同会话输入先持久入队，再依照 FIFO 顺序获得执行权。录入失败不调用模型；排队的清空历史请求等待前一条完成。页面在重新加载历史时显示未执行或待核查的输入，可复制内容以恢复工作；不会自动重放模型和工具。主动关闭此提示后，同一会话的后续输入也不会重新显示该提示。首次输入在运行前退出也会保留会话记录。只读恢复查询为 `GET /api/runs/pending?session_id=<id>`。

参考：[飞书发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)、[腾讯 OpenClaw 微信协议](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md)、[Apple 提醒事项标签](https://support.apple.com/en-ie/guide/iphone/iph474a6685c/ios)。

## 模型路由与运行事实

供应商、真实模型标识与上游协议分别绑定；会话覆盖在运行开始时解析并固定，不凭模型名猜测厂商。OpenAI Chat Completions、Anthropic Messages、Gemini Native 与 Responses 走对应协议适配器。技能和计划执行使用独立 Agent 实例，来源会话只提供模型、项目与权限设置。

输入按 FIFO 预约排队，持久录入不改变当前活动运行的模型历史。RunRecord 关联 session_id、run_id、tool_call_id、operation_id；定时执行另关联 job_run_id。Application 业务写动作记录 operation admission 和完成/未知状态，审计不复制完整工具参数。运行记录用于核查与恢复判断，不承诺完整模型请求重放。

任务中的负向约束只排除与当前交付相关的内容；排除条件静默生效，不把“已忽略什么”反复写进结果。
