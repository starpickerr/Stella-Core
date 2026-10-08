# 事务

普通事务是一个节点；只有需要拆解时才添加子事务。`parent_id` 与同级 `sort_order` 表示层级和手动顺序。`todo_dependencies` 单独保存“必须先完成”的关系，既不是子事务，也不改变父事务进度。依赖不能形成环，前置事务未完成时不能进入“进行中”或“已完成”。

状态为 `todo`、`in_progress`、`waiting`、`blocked`、`completed`、`cancelled`。`completed_at` 与状态同步，保留旧 API 的完成/撤销完成语义。父事务进度按未取消的直接子事务计算；完成父事务前检查所有后代，仍有未完成后代时要求调用方明确使用 `force`，不会级联完成子事务。删除父事务会删除其子树，页面会先确认。

系统视图依次是全部事务、即将到期、未完成和已完成；无日期事务也显示在“全部事务”中。已取消事务仅出现在“全部事务”中。旗标、标签、清单、日期、优先级是事务属性。点击事务标题进入聚焦模式，只显示当前事务和直接子事务；详细编辑表单在聚焦页内展开。`planned_on` 是计划处理日，`due_on` / `due_time` 是截止时间，`remind_at` 是独立的带时区提醒时间。原有截止时间通知和逐次重复完成继续使用原逻辑，显式提醒也进入桌面通知交付队列。重复系列按发生日期完成；因发生实例与系列层级含义不同，重复事务不能有子事务或依赖，也不能设置单次 `remind_at`。

数据保存在用户级 `todos/todos.db`。启动时只补充列和依赖表，并把旧的非空 `completed_at` 映射为 `completed`；旧记录仍是顶层事务。原有 `checklist` 保留为旧检查清单，新的拆解使用子事务。早期 `calendar_affairs` 与 `agenda_handoffs` 的迁移和来源墓碑保持原行为。简报行动条目仍同步进事务，用户修改后不被覆盖。

未来的显式 `remind_at` 会建立一条 ID 为 `todo-reminder:<todo_id>` 的一次性 scheduler 任务。任务执行时通过 `QueueTodoReminder` 命令核对事务 ID 和提醒时间，再写入现有桌面通知交付队列；改期、完成、取消或删除事务会更新或移除对应任务。事务库中的 `todo_scheduler_links` 保存待同步状态，scheduler 存储暂时不可用时由后续服务初始化重试。旧提醒在迁移时补建任务；截止时间和重复事务的既有通知逻辑保持原样。

`TodoService` 是 UI 和 Agent 共用的事务能力。旧的创建、编辑、完成、删除、列表接口仍可使用；新增 `change_todo_status`、`add_subtask`、`move_todo`、`add_dependency`、`remove_dependency`。HTTP `/api/todos` 路径与 Agent `todos` 工具都调用 Application Port 中同一个服务。自然语言任务可从事务页交给现有对话 Agent 解释，事务页不另建日期解析器。
