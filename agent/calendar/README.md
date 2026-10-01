# 日程与简报联动

日程存于当前用户的 `calendar/calendar.db`，包含 `calendar_events`、`calendar_categories` 和 `agenda_handoffs` 三张表。默认分类为个人、工作、学习、中国大陆节假日；用户可以添加分类。中国大陆节假日分类不可删除或改名，其他分类可以修改、删除；删除后已有日程变为未分类。旧版本中的空白「事务」分类会自动移除；若已有日程使用该分类，则保留这些日程和分类，允许用户自行整理。

桌面端 `/calendar` 提供日、周、月、年、列表五种视图，可按分类筛选、展开详情、创建、编辑及删除日程。周视图为周日开始的七列 0–24 点时间轴，横向连续滚动各周；月、年视图纵向连续滚动相邻周期。列表读取全部已存日程与重复系列，不受当前视图时间范围限制。可设置每天、每周（多选星期）、每月或每年重复，结束日期可选。编辑或删除重复日程会作用于整个系列。Agent 通过 `calendar` 工具使用同一数据库，支持 `list/get/create/update/delete` 和 `categories/create_category/update_category/delete_category`。所有时间都以带时区的 ISO 8601 输入，数据库统一保存 UTC；`end_at` 为不含的结束边界。重复规则保留 IANA 时区，按当地时间展开，带时间范围的 `list` 返回该范围内的实例；不带范围的 `list` 返回原始系列。

「导入日期」直接把全天日期放入同一 `calendar_events` 表。内置 2025、2026 年国务院发布的放假与调休上班安排，按年份一次导入，同年重试不会产生重复记录；官方来源分别是 [2025 年通知](https://www.gov.cn/zhengce/zhengceku/202411/content_6986383.htm) 和 [2026 年通知](https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm)。官方节假日带紫色星标、来源链接，不能编辑但可移除。用户还可手动添加特殊日期并选择每年重复，或导入不超过 1 MB、最多 500 条的 `.ics` 全天事件与含 `title,date,annual,description` 列的 `.csv`。文件导入对已有 UID 或相同名称、日期去重；不支持的 iCalendar 定时与复杂重复规则会给出错误，避免丢失时间信息。

简报生成后，`BriefingPipeline` 将精选的来源条目交给 `CalendarService.ingest_briefing`。有明确 `due_at` 或 Agent 从原文提取的 `calendar.start_at` 时创建日程；无明确时间不推测。需处理的条目写入 `agenda_handoffs` 的 `task` 目的地，供后续独立事务应用迁移；本分支不实现事务功能。一个邮件线程合并为一张简报卡时，每条被精选的来源仍单独参与联动。

来源标识用于去重。再次生成同一简报会更新未被用户编辑的来源日程，保留用户已编辑的日程，并清理本次简报不再精选的未编辑日程及交接记录。简报写入不依赖日程服务成功；联动故障写入日志，不回滚已生成的简报。
