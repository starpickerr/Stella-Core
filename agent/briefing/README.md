# 简报宿主适配

简报数据、规则、动作、不可变历史与 outbox 的唯一所有者为外仓 `stella.briefing` 插件。Core Application、HTTP 和 Agent 端口调用公开 RPC；插件缺失或停用时返回不可用，不再构造 Core BriefingService 或数据库。Core 调度器按已启用用户、以后台身份驱动插件 outbox，失败保留插件待处理记录。

Core 当前保留来源选择/抓取与 Agent 生成的适配 pipeline、进度状态及公开 DTO；这些适配通过插件公开服务提交候选、游标和完整快照，不拥有领域 SQL。来源与生成编排外移、统一 Core 模型调用和独立业务页面仍在插件化主线中实施，不能据此声明完整改造完成。
