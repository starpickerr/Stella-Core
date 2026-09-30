# 日程与简报联动

日程存于当前用户的 `calendar/calendar.db`，包含 `calendar_events`、`calendar_categories` 和 `agenda_handoffs` 三张表。默认分类为工作、个人、学习、其他；用户可以添加、修改、删除分类，删除分类后已有日程变为未分类。

桌面端 `/calendar` 提供月历与全部日程列表两种视图，可按分类筛选、展开详情、创建、编辑及删除日程。Agent 通过 `calendar` 工具使用同一数据库，支持 `list/get/create/update/delete` 和 `categories/create_category/update_category/delete_category`。所有时间都以带时区的 ISO 8601 输入，数据库统一保存 UTC；`end_at` 为不含的结束边界。

简报生成后，`BriefingPipeline` 将精选的来源条目交给 `CalendarService.ingest_briefing`。有明确 `due_at` 或 Agent 从原文提取的 `calendar.start_at` 时创建日程；无明确时间不推测。需处理的条目写入 `agenda_handoffs` 的 `task` 目的地，供后续事务模块读取，本次不创建事务。一个邮件线程合并为一张简报卡时，每条被精选的来源仍单独参与联动。

来源标识用于去重。再次生成同一简报会更新未被用户编辑的来源日程，保留用户已编辑的日程，并清理本次简报不再精选的未编辑日程及交接记录。简报写入不依赖日程服务成功；联动故障写入日志，不回滚已生成的简报。
