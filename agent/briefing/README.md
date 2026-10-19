# 简报宿主适配

简报数据、规则、动作、不可变历史与 outbox 的唯一所有者为外仓 `stella.briefing` 插件。Core Application、HTTP 和 Agent 端口调用公开 RPC；插件缺失或停用时返回不可用，不再构造 Core BriefingService 或数据库。Core 调度器按已启用用户、以后台身份驱动插件 outbox，失败保留插件待处理记录。

Core 宿主 pipeline 只负责来源选择/抓取、进度状态、Agent 起草（模型边界仍在 Core）及公开 DTO；持久化统一经插件 `run_pipeline`（预抓取 `sources` + 可选 `draft`），不再由宿主直接 `stage_*` / `complete_briefing`。统一 Model Service 调用面与独立业务页面仍在插件化主线中实施，不能据此声明完整 G5 完成。
