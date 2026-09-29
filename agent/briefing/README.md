# 每日简报

桌面端从 IMAP 邮件生成每日简报，展示每日历史、正文和「需处理 / 知会」条目。条目支持待处理、已处理、忽略、需跟进四种状态；过滤规则支持创建、编辑、启停和删除。

## 桌面使用

1. 打开「简报」，点击右上角设置按钮，填写 IMAP 服务器、邮箱账号、邮箱授权码、SSL 端口和文件夹，保存后立即生效。
2. 当天没有简报时点击「生成今日简报」；已有简报时按钮变为「更新今日简报」。每天只有一份主简报，标题如 `2026年9月9日·简报`。在条目右侧修改处理状态。
3. 详情展示内容时间窗口；在「更新历史」中选择版本可查看完整正文、条目及当时的处理状态，历史快照只读。
4. 在设置中添加保留或排除规则。规则按发件人、发件地址、发件域名、标题或邮件列表 ID 匹配，支持等于或包含；匹配不区分大小写，保留规则优先。
5. 修改规则后更新今日简报。已经同步过的候选邮件仍会重新过滤，已有条目的处理状态不会被重置。

首次生成默认回看最近两天；后续增量同步会读取全部新增邮件，候选目录按内容窗口筛选。默认排除 noreply 和含 List-Unsubscribe 的邮件；保留规则可以覆盖这些默认过滤。正文摘要来自邮件前 64 KiB 的纯文本或 HTML 文本，最长 500 字符，不展示附件内容。使用只读邮箱和 BODY.PEEK，不标记邮件为已读。

目前使用关键词将邮件分为需处理和知会，按处理优先级和时间排序，合并邮件线程后最多展示 10 条。日历、待办、自动催办和会前准备尚未接入。

## 配置与存储

没有本地邮箱配置时，从后端环境变量读取初始配置：

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `IMAP_HOST` | IMAP 服务器 | 必填 |
| `IMAP_USER` | 邮箱账号 | 必填 |
| `IMAP_PASSWORD` | 邮箱授权码 | 必填 |
| `IMAP_PORT` | SSL 端口 | `993` |
| `IMAP_FOLDER` | 邮件文件夹 | `INBOX` |

设置页保存的本地配置优先于环境变量，保存在当前用户的 `briefing/mailbox.json` 中。文件以原子替换方式保存，POSIX 权限为 `0600`。密码不会返回客户端或写入简报数据库；再次保存时密码字段留空会保留已有授权码。连接通过系统 CA 验证 SSL 证书，Python 3.9+ 的连接与读写超时为 30 秒。

简报、候选目录、规则和同步游标保存在 `common.state_dir.briefing_db()` 解析的用户级 `briefing/briefing.db` 中。单用户安装默认位于工作区；多身份布局会按用户隔离。切换账号、服务器、端口或文件夹会使用独立的同步游标。

每日主简报沿用 `morning` 类型和既有 ID 以兼容旧数据，同日更新复用 ID。文档、条目和不可变的版本快照在同一事务中保存，失败重试保留此前成功生成的正文和条目；同进程共享存储的运行串行执行，游标在成功保存后推进。

## 内容时间窗口与定时生成

新一天的窗口从上一份简报最后一次成功生成/更新的时间开始，到本次运行开始时间结束，采用 `(起点, 终点]`，避免边界邮件重复。例如 6 日 13:00 更新后，7 日 08:00 生成的简报覆盖 6 日 13:00 至 7 日 08:00。当日更新保留初始窗口起点、延长终点，因此当天内容仍完整保留。失败尝试记录在更新历史中，不推进成功的窗口终点。

桌面后端启动内置调度，每天本地时间 **08:00** 自动生成当天缺失的主简报，无需配置 AI 任务或 Agent 模型。当天已有成功生成（含部分成功）的简报时跳过，手动更新仍然可用。邮箱未配置时等待配置；失败后每五分钟重试。保持后端运行才能在 08:00 执行；关闭、休眠或错过执行时，在 08:00 之后启动/唤醒会补生成当天简报，不逐日补造离线期间的文档，时间窗口仍覆盖离线间隔。

已有数据库自动补充窗口和版本表，并将当前保留下来的内容作为「迁移保留」版本。升级前被覆盖的历史无法恢复；之后每次生成/更新均可追溯。

## 开发结构

- `store.py` / `schema.sql`：SQLite 目录、候选关联与快照。
- `service.py`：参数校验、状态与规则操作、原子完成简报。
- `scheduler.py`：本地 08:00 调度、补生成和失败重试。
- `settings.py`：用户级邮箱配置，不依赖 Agent 模型。
- `sources/email.py`：IMAP 增量拉取与 MIME 解析。
- `rules.py` / `compose.py` / `pipeline.py`：过滤、合并、正文生成、落库和游标提交。
- `agent/tools/briefing/briefing_tool.py`：聊天与调度使用的薄适配器。
- `desktop/src/renderer/src/pages/briefing/`：桌面历史、详情、条目和设置组件。

桌面客户端通过既有 Python HTTP 服务调用以下接口，均使用现有认证机制。Web 页面不在维护范围。

| 方法 | 路径 | 操作 |
| --- | --- | --- |
| GET | `/api/briefings` | 历史，可按 `kind` / `status` 筛选 |
| POST | `/api/briefings/run` | 生成/更新，支持 `operation=create/update/upsert`、`kind` / `briefing_date` |
| GET | `/api/briefings/{id}` | 当前正文、条目与更新历史摘要 |
| GET | `/api/briefings/{id}/revisions/{number}` | 指定版本的完整快照 |
| POST | `/api/briefings/items/status` | 更新条目 `id` / `status` |
| GET / POST | `/api/briefings/rules` | 查询 / 创建规则 |
| POST | `/api/briefings/rules/update` | 编辑或启停规则 |
| POST | `/api/briefings/rules/delete` | 删除规则 |
| GET / POST | `/api/briefings/settings` | 查询 / 保存邮箱配置 |

HTTP `status=success` 表示请求完成；生成结果还需检查 `briefing.status`（`completed`、`partial`、`failed`）。失败原因显示在详情中。工具端生成失败会返回失败结果。

## 验证

```bash
python -m pytest tests/test_briefing*.py tests/test_state_dir.py -q
cd desktop
npm run typecheck
npm run build
```

测试使用临时 SQLite 数据库、静态邮件源或模拟 IMAP，不读取真实邮箱。打包时需要重新构建 Python 后端，`desktop/build/stella-backend.spec` 已包含简报 schema；仅构建 renderer 不会更新已安装应用的后端。
