# 日程与简报联动

日程存于当前用户的 `calendar/calendar.db`，包含 `calendar_events`、`calendar_categories` 和 `agenda_handoffs` 三张表。默认分类为个人、工作、学习、中国大陆节假日；用户可以添加分类。中国大陆节假日分类不可删除或改名，其他分类可以修改、删除；删除后已有日程变为未分类。旧版本中的空白「事务」分类会自动移除；若已有日程使用该分类，则保留这些日程和分类，允许用户自行整理。

桌面端 `/calendar` 提供日、周、月、年、列表五种视图，可按分类筛选、展开详情、创建、编辑及删除日程。周视图为周日开始的七列 0–24 点时间轴，横向连续滚动各周；月、年视图纵向连续滚动相邻周期。列表读取全部已存日程与重复系列，不受当前视图时间范围限制。可设置每天、每周（多选星期）、每月或每年重复，结束日期可选。编辑或删除重复日程会作用于整个系列。Agent 通过 `calendar` 工具使用同一数据库，支持 `list/get/create/update/delete` 和 `categories/create_category/update_category/delete_category`。所有时间都以带时区的 ISO 8601 输入，数据库统一保存 UTC；`end_at` 为不含的结束边界。重复规则保留 IANA 时区，按当地时间展开，带时间范围的 `list` 返回该范围内的实例；不带范围的 `list` 返回原始系列。

「导入日期」直接把全天日期放入同一 `calendar_events` 表。内置 2025、2026 年国务院发布的放假与调休上班安排，按年份一次导入，同年重试不会产生重复记录；官方来源分别是 [2025 年通知](https://www.gov.cn/zhengce/zhengceku/202411/content_6986383.htm) 和 [2026 年通知](https://www.gov.cn/zhengce/zhengceku/202511/content_7047091.htm)。官方节假日带紫色星标、来源链接，不能编辑但可移除。用户还可手动添加特殊日期并选择每年重复，或导入不超过 1 MB、最多 500 条的 `.ics` 全天事件与含 `title,date,annual,description` 列的 `.csv`。文件导入对已有 UID 或相同名称、日期去重；不支持的 iCalendar 定时与复杂重复规则会给出错误，避免丢失时间信息。

日程业务规则和数据库唯一写入者为外仓 `stella.calendar` 插件，Core 的 Application、HTTP、Agent 和 Apple 适配统一通过公开 RPC 调用。插件未安装或停用时返回不可用，不启动旧日程实现。简报通过公开动作创建、关联或同步来源事件；同源幂等，保留用户修改，删除保留墓碑，失败由简报 outbox 记录并重试。

## Apple 日历连接

macOS 桌面端的日程页提供「Apple 日历」入口。首次使用时点击「请求日历权限」，在 macOS 授予完整日历访问权限，选择要同步的日历和方向，再点击「连接并同步」。首次连接只导入所选 Apple 日历；连接前已有的 Stella 自有日程不会被批量上传。之后新建的 Stella 日程会在自动或手动同步时写入第一个选中的可写日历。仅导入、仅导出、双向三种方向均可切换。断开连接会停止后续同步，已有 Stella 日程和 Apple 事件均保留。

EventKit 访问由 `native/apple-calendar/CalendarBridge.swift` 中的独立 Swift 进程完成。Python 的 `apple_bridge.py` 以 JSON stdin/stdout 调用原生进程，`apple_sync.py` 在用户的 `calendar/apple_sync.db` 保存选择、事件映射、内容指纹、冲突与最近成功同步时间；业务日程一律经 `Application.port("calendar")` 读写。原生进程监听 `EKEventStoreChanged`，Python 另以五分钟周期重试。只读取所选日历、当前日期前一年到后两年的事件实例；下一次同步会随日期推进窗口。重复事件的各实例与例外按原始发生日期独立映射，以保留移动后的例外。Stella 自建重复系列在 Apple 端出现单次修改时，Stella 保留系列并以独立日程替换被修改的那一次；无法安全映射的整组系列冲突需要人工处理，不会静默折叠成单次日程。

Apple 事件删除须在连续、间隔至少一分钟的完整读取中被确认；日历不可用时清除待删除判定。Stella 删除的关联日程不会触发自动删除 Apple 事件，用户须在连接面板明确点击「确认删除 Apple 事件」。两边同时修改时记录冲突，用户可选择保留 Stella 或 Apple 版本。来源事件内容不会写入普通同步日志。同步失败不会阻断日程查询和其他业务。

连接后，每日简报的来源列表增加只读「Stella 日程」，读取未来一天的日程候选；Agent 原有 `calendar` 工具可查询和操作同步后的日程。非 macOS 平台会显示不支持状态。开发环境运行 `npm run dev` 会编译 Swift helper；macOS 分发运行 `npm run dist:mac` 时会将 helper 和授权说明打入应用。
