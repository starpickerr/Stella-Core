# 代码现状与实施线索

以下依据 2026-10-11 的代码核查，描述的是**当前实现**，不是本轮完成状态。目标和验收以 [需求与验收](requirements.md) 为准。

## 已有入口

- `desktop/src/renderer/src/pages/SecurityPage.tsx`：安全中心目前有独立 `secrets` 标签页。该页先列出 `center.secrets` 并调用 `deleteSecuritySecret` 删除，接着显示固定服务下拉、密钥输入和 `saveSecuritySecret`，最后还有通过 `updateConfig({ web_password })` 修改应用访问密码的卡片。“总览”已有 `secret_count` 统计，可承接精简清单。
- `desktop/src/renderer/src/pages/securityLocale.ts`：`commonCredentials` 固定列出 OpenAI、DeepSeek、Gemini、Claude、GitHub、LinkAI、千帆、Moonshot、DashScope 九项；另有“其他凭据”。这不是模型页厂商目录。删除表单后同步清理失效的表单文案，保留并更新清单相关双语文案。
- `desktop/src/renderer/src/pages/settings/ModelsTab.tsx`：模型设置已有内置及自定义厂商的密钥录入、修改和清除入口；`SettingsPage.tsx` 支持 `/settings?tab=models` 及返回来源状态。`GeneralSettings.tsx` 已有 `web_password` 编辑入口。
- `desktop/src/renderer/src/api/client.ts`：安全凭据现有 `saveSecuritySecret`、`deleteSecuritySecret` 客户端调用；后端 `channel/desktop/desktop_channel.py` 的 `SecuritySecretsHandler` 提供 POST 和 DELETE。移除界面新增路径时检查调用方；本轮不要求为非模型凭据另建编辑器，也不要求凭据迁移。

## 清单与删除的现状差异

- `agent/permission/center.py` 的 `secrets()` 遍历配置中非空且字段名以 `_api_key`、`_token` 结尾的顶层值，并合并 `_env_keys()`。当前 `_env_keys()` 只验证变量名格式，**没有过滤后缀，也没有检查值是否非空**；这与目标清单范围不一致。
- `custom_providers` 的密钥保存在模型配置的嵌套列表中（见 `models/custom_provider.py`），当前 `secrets()` 不会遍历它们。列表要能够区分多个自定义厂商；删除某个密钥时不能删掉整个自定义厂商记录。
- `center.set_secret()` 目前对已知模型字段写顶层模型配置，对其他名称写 `.env`；模型字段删除时会尝试清除 `.env` 同名项。实施时还须核对运行时环境变量同步、模型页状态以及多来源去重，不能只把行从前端列表中隐藏。
- `SecuritySecretsHandler` 的现有响应只返回名称、来源、配置状态，不返回明文。更新接口或数据结构仍应保持这个边界。不要因为 UI 删除了录入表单就移除工具的凭据路径保护。
- `tests/test_security_center.py` 已有 `test_model_secret_status_and_revoke_without_plaintext`，可作为隔离数据测试起点；新增覆盖空值、普通变量、自定义厂商、双来源、删除后重启和跨模型设置状态的行为测试。测试前核对共享配置与环境变量的隔离方式。

## 产品解释

安全中心的清单展示“现在存了什么、存在哪”，不表示列出的都是 Stella 支持的模型厂商；未保存的厂商不应为了凑齐目录而出现。对于模型密钥，安全中心与模型设置读写的是同一配置。应用访问密码是浏览器登录开关相关设置，不属于服务密钥。终端和文件读取密钥的限制由现有权限/凭据路径保护实现，而非安全中心的录入表单。

## 权限分层的代码现状

- `agent/permission/security_policy.py` 定义三种预设、自定义和当前 **11 项**规则；`resolve()` 顺序读取默认、项目、对话，`merge()` 当前按字段合并，后层与前层预设相同时可能保留前层的规则差异。新需求要求本层保存的方案完整覆盖前层方案，同时兼容旧的部分差异记录，不能直接改变旧数据的安全效果。
- `agent/permission/center.py` 的 `overview(session_id, agent_id)` 回传全局、项目、对话原始策略与最终方案，但当前安全页只把正在打开的 `activeId` 传入。`desktop/src/renderer/src/pages/SecurityPage.tsx` 的“项目与对话”只选项目；对话区域跟随活动对话，并在项目和对话各自展开 `PolicyEditor`。`overrideSummary` 只显示规则差异，没有展示实际生效的具体方案名。
- 同一页面的“默认权限”四选项中，点击“自定义”会立即 `saveGlobal()` 并复制规则，尚未点击“保存自定义”就持久化。项目和对话的 `PolicyEditor` 可在继承或预设状态下展开；需改为仅本层自定义已保存时稳定展示，或选择自定义后的未保存草稿。
- `desktop/src/renderer/src/components/PermissionSelector.tsx` 是输入框的权限芯片。点击自定义会立刻把当前有效规则写成对话策略；“设为项目默认”按 `mode` 和有效规则写入项目，另有“设为全局默认”快捷操作；“恢复继承”把整份对话策略设为 `null`。芯片提示当前混入了 `authorized_roots`，与独立目录授权要求不符。
- `channel/desktop/desktop_channel.py` 的 `SecurityPolicyHandler` 接收目标层级写入；`SessionSettingsHandler` 维护输入框读写的对话设置。`desktop/src/renderer/src/store/sessionSettingsStore.ts` 缓存当前对话权限，`useSessionStore` 有对话列表和项目归属。实现时让安全页显式选中对话，并核对两个入口保存后彼此刷新；项目选择和对话选择不能共用一个隐式活动上下文。
- `agent/workspace/project_store.py`、`agent/workspace/session_prefs.py` 分别持久化项目与对话策略。`extra_roots` 与方案同处策略对象；实施“恢复继承”或修改目录时需分开处理，不得顺带删除独立目录授权或制造一个自定义方案。
- `tests/test_security_center.py` 已覆盖部分分层合并与旧配置迁移。新增测试应覆盖不同层的预设覆盖、继承具体名称、旧规则差异不放宽、未保存自定义不落盘、非当前对话写入、项目默认、恢复继承及目录保留；前端还需验证实际交互。

## 外部连接、总览与活动的现状

- `agent/permission/center.py` 的 `connections()` 先写死 GitHub、Email、Calendar、Browser、Plugins、External API 六项，Browser 恒为 `connected=True`，Plugins/External API 恒为 `False`；Email/Calendar 分别看 `email_password`、`calendar_token` 等通用字段，不读取简报邮箱或 Apple 日历的实际状态。GitHub 仅看令牌是否存在；MCP 再依据配置和 `ToolManager.list_mcp_status()` 添加实例。`overview()` 的 `connection_count` 计入已连接且未暂停的条目，因此浏览器会抬高数量。
- 同一函数从安全活动的 `resource` 与连接 `id` **完全相等**的记录推算 `last_access`，但 `agent/permission/gateway.py` 对外部调用还可能记录工具名、资源类别或 `external_api`，因此“尚未使用”不能证明没有使用。`SecurityPage.tsx` 在 `scopes` 为空时仍显示“全部操作”；真正明确的 `*` 与未知范围没有区分。
- `agent/briefing/settings.py` 的 `public_mailboxes()` 可提供简报邮箱配置和启用状态，连接测试在同一模块；Apple 日历真实授权与配置由 `/api/calendar/apple/status` 和设置页 `AppleIntegrations.tsx` 管理。需要区分“配置存在”“已验证可用”和“权限允许使用”，不能用一个布尔值概括。
- `SecurityPage.tsx` 总览标题按 `summary.status` 显示正常或待查看，标题下却始终渲染 `process_isolation.reason`；隔离不可用时还会覆盖总览状态标题。`agent/permission/center.py` 会把中文限制附加到隔离原因上，其他隔离原因为英文。已有 `securityLocale.ts` 的 `statusNormalHelp`、`statusAttentionHelp` 可作为状态说明入口。
- `securityLocale.ts` 的 `tools` 翻译表只有部分工具；活动列表、过滤器和待确认操作对表外工具直接显示原始 id。`agent/tools/catalog.py` 已有内置工具的双语展示名称，可用作共享目录；动态 MCP 工具仍需真实显示名与安全回退。

## 定时任务运行权限的现状

- `desktop/src/renderer/src/pages/TasksPage.tsx` 的运行权限下拉只含“沿用／只读／工作区写入／完全访问”；任务卡片用 `run_permission_mode` 原值标注“沿用”，不显示具体生效方案。`agent/scheduler/mutations.py` 仅允许用户保存三种显式预设，`inherit` 在存储中变成没有该字段。
- `agent/scheduler/conversation.py` 当前有 `source`（已有对话）、`reuse`（任务复用对话）、`new`（每次新建对话）三种桌面执行方式，但 `validate_conversation_action()` 拒绝非 `web` 渠道上的对话选择。`TasksPage.tsx` 只在 `channel === 'web'` 时显示这些选择，切到其他发送渠道时 `buildAction()` 会删除 `conversation_mode`、`source_session_id` 等字段。新需求要求执行对话和发送渠道独立：三个执行方式不随客户端、Telegram Bot、企业微信智能机器人等通知渠道切换而丢失；绑定已有对话与消息投递目的地是不同字段和不同判断。
- 用户本轮把“沿用”限定为**明确绑定已有对话**，即须保存且验证 `source_session_id`；`reuse`、`new` 或仅在创建时恰好打开某条对话，都不能算绑定。`agent/runtime/tool_invocation.py` 运行时会先通过 `resolve()` 读取执行会话的默认、项目、对话策略，`scheduled_permission_scope()` 有显式预设时会覆盖当次运行。当前“沿用”在有可解析执行会话时实际经过共享策略，但 UI 未区分是否明确绑定，也不显示具体结果；新要求需把资格与执行目标绑定一致。
- 定时任务权限是一次运行的覆盖，不应把所选值写回全局、项目或对话策略；当前没有任务级自定义规则存储，本轮也不新增。绑定对话可通过共享三层方案沿用自定义规则，未绑定任务只选三种显式预设。当前还没有把任务的实际权限状态返回给列表/编辑器；后续实现须明确执行会话来源、失效处理以及与前述三层权限语义的一致性。客户端通知、外部渠道投递与执行对话的结果记录须分别核对，不能用切换渠道来暗改绑定。
