# 能力页面实施参考：内置工具目录、双语文案和完整介绍

本文配合 [需求与验收](requirements.md#6-进化页面更新为能力) 使用。它记录 2026-10-10 的代码现状与可直接采用的首版用户文案；修改代码前仍应以当前分支的实现核对工具能力。本文不表示页面已经实现。

## 已核对的代码入口

| 范围 | 当前入口与问题 |
| --- | --- |
| 入口与路由 | `desktop/src/renderer/src/layout/NavRail.tsx` 使用 `menu_evolution`；`desktop/src/renderer/src/App.tsx` 的页面地址为 `/skills`；`desktop/src/renderer/src/i18n.ts` 的页面标题为 `skills_title`。 |
| 列表 | `desktop/src/renderer/src/pages/SkillsPage.tsx` 同时展示工具与技能。两个卡片的介绍均使用 `line-clamp-2`；工具标题显示机器名，工具和技能都没有详情入口。 |
| 前端语言 | `desktop/src/renderer/src/i18n.ts` 的 `getLang()`、`setLang()` 控制 `zh`／`en`；已有 `localizedLabel` 可读取 `{zh,en}` 文案。`desktop/src/renderer/src/api/client.ts` 的 `getTools()` 当前没有传语言。 |
| 工具接口 | `channel/desktop/desktop_channel.py` 的 `ToolsHandler` 只遍历 `ToolManager.tool_classes` 并返回 `{name, description}`；`desktop/src/renderer/src/types.ts` 的 `ToolInfo` 也只有这两个字段。接口按后端全局语言处理，英文仅对 `scheduler` 有特例。 |
| 目录完整性 | `agent/tools/__init__.py` 的 `__all__` 有 24 个内置工具类候选（排除 `BaseTool`、`ToolManager`、`McpTool`）。`agent/tools/tool_manager.py` 故意跳过 `MemorySearchTool`、`MemoryGetTool`；`bridge/agent_initializer.py` 在创建 Agent 时另行注入这两项。可选依赖与配置还会影响运行时可用性。 |
| 工具原始描述 | `agent/tools/*` 的 `description` 是给 Agent 的调用说明，中英混用，部分含参数指令和运行时内容。它不适合直接做用户文案；尤其不能为了取记忆工具描述而无记忆管理器地实例化它们。 |

## 用户可见行为与数据边界

1. 内置工具目录以稳定工具 ID 为键；标题、介绍及详情内容分别保存 `zh`、`en` 文案。界面按当前 `getLang()` 选择，切换语言后列表、已展开内容和详情页同步更新。机器 ID 只在展开或详情中作为辅助信息展示，不代替本地化标题。不得自动机器翻译或以另一语言文本填充缺失字段。
2. 建议由同一份内置工具目录元数据供应列表与详情，避免两套名称和内容漂移。目录覆盖下表全部 24 项，新增内置工具时同步补齐中英文并由测试检查。运行时可用状态另算：未配置、缺依赖、被功能开关禁用、需特定 Agent 上下文等都仍显示在目录里，原因用当前语言说明。目录不会改变 Agent 的工具注入、权限检查或实际可调用性。
3. `/api/tools` 可扩充或新增只读目录接口，返回稳定 `id`、`title: {zh,en}`、`intro: {zh,en}`、`detail: {zh,en}`、可用状态及本地化原因；接口只返回公开的能力说明，不能返回凭据、用户数据、内部提示词或未经筛选的工具参数。前端选择语言，避免后端全局语言与桌面客户端当前语言不同步。外部 MCP 工具不计入内置目录。
4. 工具和技能条目默认折叠：整行可操作，视觉上只有本地化标题与展开箭头；技能原有启停开关放在展开区域。展开后显示不截断的完整介绍、状态与“查看详情”；再次操作可收起。展开不调用工具、不改变技能启停。介绍很长时自然换行并允许滚动，窄窗口也能读完。
5. 工具和技能都提供可直接打开的详情地址；保留现有 `/skills` 列表地址，可采用 `/skills/tools/:id`、`/skills/skills/:id` 或等价路由。工具详情展示完整介绍、适用条件／限制、状态和稳定 ID，必要时列出经过筛选且有翻译的功能说明；技能详情展示完整描述、来源与启停状态。不得直接渲染原始 Agent `description`、未经清理的技能正文或敏感配置。返回列表后保留原展开项和可见位置；无效 ID 显示可返回的未找到状态。
6. 折叠控件使用按钮与 `aria-expanded`，支持 Enter／空格键，标题获得完整可访问名称；详情入口是独立链接，技能开关也独立操作。三者点击互不误触。加载、空列表、错误与重试分开处理；一个请求失败不能把另一个请求已成功的数据清掉。

## 24 个内置工具的首版双语目录

此表的 ID 与源码 `name` 一致，中文／英文标题和介绍可直接用作列表文案。详情页至少完整展示对应介绍，并按工具实际行为补充本地化的适用条件与限制。不要把原始 Agent 调用说明直接复制到界面。新增、删除或改名工具时同步更新此表及目录一致性测试。

| ID | 中文标题 | English title | 中文介绍 | English intro |
| --- | --- | --- | --- | --- |
| `read` | 读取文件 | Read Files | 读取工作区中的文件内容，并查看支持的文档内容或媒体文件信息。 | Read workspace files, supported documents, and media file information. |
| `write` | 写入文件 | Write Files | 创建文件或完整重写文件内容。 | Create files or replace an entire file's contents. |
| `edit` | 编辑文件 | Edit Files | 按指定文本修改已有文件，适合局部编辑。 | Change existing files by replacing specific text. |
| `bash` | 执行命令 | Run Commands | 在工作环境中执行命令并读取输出。 | Run commands in the workspace and read their output. |
| `ls` | 浏览目录 | List Directory | 查看目录中的文件和子目录。 | Browse files and subdirectories in a directory. |
| `send` | 发送本地文件 | Send Local Files | 将本地图片、音视频或文档作为文件发给用户。 | Send a local image, media file, or document to the user. |
| `search_files` | 搜索文件 | Search Files | 在工作区中按名称或内容查找文件。 | Find workspace files by name or content. |
| `memory_search` | 搜索记忆 | Search Memory | 检索 Agent 的长期记忆；启用知识库时也可检索知识内容。 | Search the agent's long-term memory and, when enabled, knowledge base. |
| `memory_get` | 读取记忆 | Read Memory | 读取指定记忆文件或行段；启用知识库时也可读取知识页面。 | Read a memory file or line range and, when enabled, knowledge pages. |
| `evolution_undo` | 撤销自主学习 | Undo Self-Learning | 根据已有备份撤销一次自主学习对记忆或技能文件的修改。 | Restore memory or skill files from a backup before a self-learning change. |
| `subagent` | 分派子任务 | Delegate Task | 将独立工作交给子 Agent 执行并汇总结果。 | Delegate independent work to a subagent and collect its result. |
| `bills` | 管理账单 | Manage Bills | 记录、查询和维护个人收支，并查看月度或年度汇总。 | Record and manage personal income and expenses, with monthly or yearly summaries. |
| `briefing` | 管理简报 | Manage Briefings | 生成、更新和查看每日简报，并管理简报条目与规则。 | Generate, update, and inspect daily briefings, items, and rules. |
| `calendar` | 管理日程 | Manage Calendar | 查看、创建和维护个人日程及分类，包括重复日程。 | View and manage personal events and categories, including recurring events. |
| `apple` | Apple 集成 | Apple Integration | 查询和管理 Apple 日历、提醒事项的连接及同步操作。 | Manage Apple Calendar and Reminders connections and sync operations. |
| `todos` | 管理事务 | Manage Tasks | 创建、拆解、排序和更新事务及其状态。 | Create, break down, order, and update tasks and their status. |
| `elearning` | 读取课程资料 | Read Course Materials | 查询 eLearning 课程信息与文件，并在授权后保存课程文件。 | Read eLearning course information and files, and save files when authorized. |
| `skill` | 管理技能 | Manage Skills | 创建或更新 Stella 自定义技能及其资源。 | Create or update Stella custom skills and their resources. |
| `env_config` | 管理密钥配置 | Manage Key Settings | 查看或更新受保护的 API 密钥和相关配置。 | View or update protected API keys and related settings. |
| `scheduler` | 管理定时任务 | Manage Scheduled Tasks | 创建、查询和维护提醒或周期性任务。 | Create, inspect, and manage reminders or recurring tasks. |
| `web_search` | 网页搜索 | Search the Web | 使用已配置的搜索服务查找实时网页信息。 | Find current web information through a configured search provider. |
| `web_fetch` | 读取网页 | Read Web Content | 获取网页正文或受支持的在线文档内容。 | Retrieve readable web pages or supported online documents. |
| `vision` | 图像识别 | Analyze Images | 分析本地或在线图片，识别内容或提取文字。 | Analyze local or online images and extract content or text. |
| `browser` | 操作浏览器 | Control Browser | 浏览网页并与页面元素交互，读取页面内容。 | Navigate pages, interact with elements, and read web content. |

## 开发和验证顺序

1. 先写目录一致性测试：对照内置导出类、独立注入的记忆工具和现有运行时清单；断言 24 个 ID 无遗漏、无重复，且 MCP 不混入。可选依赖缺失时目录仍完整、状态如实显示。若源码增减工具，以新真实清单为准更新表与测试，不把“24”硬编码为永远不变的产品规则。
2. 写接口和本地化测试：每个 ID 都有非空的 `zh`、`en` 标题、介绍和详情；两种语言均可取到，切换语言不改变 ID 与状态；请求失败不返回假空数组。验证返回内容不含凭据或用户数据。
3. 写界面交互测试再实现：初始折叠、展开全文、再次收起、进入详情与返回、技能启停、语言切换、超长介绍、窄窗口、键盘和错误重试。重点确认没有 `line-clamp-2` 或其他正文省略截断。
4. 按仓库要求运行增量检查并用实际桌面／浏览器界面验证关键交互。测试使用隔离数据与账户，不改动真实用户设置。
