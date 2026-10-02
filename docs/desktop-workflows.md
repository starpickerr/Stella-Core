# Electron 桌面业务工作流

Stella 的桌面页面通过本机 Python API 操作业务库。事务、日程、账单和健康数据按用户目录保存；自动化计划与 JobRun 按 Agent 保存。单 Agent 旧安装保持原路径，多 Agent 前需运行用户数据迁移。

## 事务与安全

事务可以设置计划处理日期（与截止日期分开）、清单、标签、旗标和检查项。焦点视图按今天、即将到期、旗标与清单筛选。重复事务的完成状态和检查项按 occurrence 日期隔离；编辑模板不会把别的实例标为完成。

安全页可修改全局工具权限，聊天里的会话权限覆盖全局设置。定时运行会在执行时读取来源会话的项目和权限；未绑定会话时使用 Agent workspace 和全局权限。修改密码需要重新认证。只读模式拒绝业务写工具与未分类的外部工具。

## 定时任务与投递

任务页支持 cron、interval（至少60秒）和 once，动作可以是固定消息或 Agent 任务。已有 tool_call、skill_call、application_command 和静默每日简报的完整 action 元数据保留可读；修改名称、时间或开关不会丢弃工具参数。

选择已配置的客户端、飞书或微信渠道，再设置接收人。执行来源与投递目标独立：修改目标不会改动来源会话的模型、项目和权限。切换渠道会移除旧渠道的接收标识元数据。

- 客户端接收人是 conversation/session ID；目标会话轮询就绪后才投递。
- 飞书需要已配置并连接的应用、发送权限和接收人可访问范围。用户可使用 Open ID、User ID、Union ID 或邮箱；群聊使用 Chat ID。请匹配“接收方式”和真实标识。
- 微信接收人必须先向机器人发送消息，建立服务器提供的 context token。应用重启后可能需要重新建立会话。缺 token 会明示不能投递；发送被拒时查看渠道状态或重新登录。渠道协议的登录状态和 token 由服务器决定。

执行成功的完整结果先保存到用户 runs 目录，再投递。投递失败会保留原计划发生实例并只重试发送，不重跑已成功的模型或有副作用工具。明确执行失败或结果未知会停用任务，记录 failed/outcome_unknown；核对目标业务状态后再决定是否手动运行。手动运行生成独立 JobRun，不改变下一次计划时间。渠道缺少端到端幂等保证，超时后重发仍可能产生重复消息。

## 保存但未运行的聊天输入

同会话输入先持久入队，再依照 FIFO 顺序获得执行权。录入失败不调用模型；排队的清空历史请求等待前一条完成。页面在重新加载历史时显示未执行或待核查的输入，可复制内容以恢复工作；不会自动重放模型和工具。首次输入在运行前退出也会保留会话记录。只读恢复查询为 `GET /api/runs/pending?session_id=<id>`。

## 本地健康导入

在 iPhone 的“健康”应用中点头像，选择“导出所有健康数据”，把文件传到本机。桌面健康页接收 Apple Health XML 或包含单个 `export.xml` 的 ZIP，也接受 UTF-8 CSV。macOS 桌面不能直接读取 iPhone HealthKit；自动/实时同步需要另行开发经过用户授权的 iPhone 伴侣应用。本轮实现本地文件导入，没有实时 HealthKit 接入。

单次上传最大32 MiB，ZIP展开总量最大128 MiB，最多500000条样本。ZIP只读取成员内容，不解压到文件系统。XML接受 Apple 导出的内部结构声明，拒绝实体和外部 DTD/资源引用，并限制嵌套深度与节点数量。整份文件校验通过后才在一笔数据库事务中写入；失败不会留下部分样本。

CSV 表头与示例：

```csv
type,source,device,unit,value,start,end,created
steps,iPhone,iPhone,count,5800,2026-10-02T00:00:00+08:00,2026-10-02T23:59:00+08:00,
weight,Scale,Scale,kg,64,2026-10-02T08:00:00+08:00,,
heart_rate,Watch,Watch,count/min,72,2026-10-02T08:00:00+08:00,,
sleep,Watch,Watch,,asleep,2026-10-02T00:00:00+08:00,2026-10-02T07:00:00+08:00,
```

必须有 type、source、value、start；日期需带时区，end为空表示瞬时样本，created可留空。Apple标准 Record 的类型、来源、设备、单位和值均保留；未知类别保留原值，不作医学推断。数量类型需有限数值。

导入按规范化样本指纹去重，原始时间和单位仍保留展示。汇总默认分别显示来源、设备、单位，不把 iPhone 与 Apple Watch 的步数相加；睡眠将 asleep、core、deep、REM区间取并集，排除 InBed 与 Awake，以免分期或总睡眠样本重复累计。步数显示合计，其余数量指标显示平均。页面展示数据中最近30天的最多500组汇总、最近100条原始样本和最近100次导入。数据默认只在本地显示，不自动交给模型。

删除某次导入后，没有其他导入引用的样本同时删除；重复导入引用的样本保留到最后一个引用删除。健康库位于 `user_root/health/health.db`，其他用户不能读取或删除该用户的导入。

参考：[Apple 健康数据导出](https://support.apple.com/guide/iphone/share-your-health-data-iph5ede58c3d/ios)、[飞书发送消息](https://open.feishu.cn/document/server-docs/im-v1/message/create)、[腾讯 OpenClaw 微信协议](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md)、[Apple 提醒事项标签](https://support.apple.com/en-ie/guide/iphone/iph474a6685c/ios)。

## 模型路由与运行事实

供应商、真实模型标识与上游协议分别绑定；会话覆盖在运行开始时解析并固定，不凭模型名猜测厂商。OpenAI Chat Completions、Anthropic Messages、Gemini Native 与 Responses 走对应协议适配器。技能和计划执行使用独立 Agent 实例，来源会话只提供模型、项目与权限设置。

输入按 FIFO 预约排队，持久录入不改变当前活动运行的模型历史。RunRecord 关联 session_id、run_id、tool_call_id、operation_id；定时执行另关联 job_run_id。Application 业务写动作记录 operation admission 和完成/未知状态，审计不复制完整工具参数。运行记录用于核查与恢复判断，不承诺完整模型请求重放。

任务中的负向约束只排除与当前交付相关的内容；排除条件静默生效，不把“已忽略什么”反复写进结果。
