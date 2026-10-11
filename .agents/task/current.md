# 代码现状与实施线索

以下依据 2026-10-11 的代码核查，描述的是**当前实现**，不是本轮完成状态。目标和验收以 [需求与验收](requirements.md) 为准。目前只更新文档，不修改这些实现。

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

## 权限分层与入口的现状差异

- `agent/permission/security_policy.py` 的 `resolve()` 按默认 → 项目 → 对话合并权限。当前 `merge()` 在下层选择与上层相同的 `preset` 时不会清空上层 `rules`，因此可能把上层自定义差异带进下层预设；新需求要求本层自己的方案完整覆盖前一层的方案。现有项目/对话数据可能只有部分规则差异，实施时需保留这些记录原来的有效限制，不能简单丢弃差异。
- 同文件的 `RULES` 与 `desktop/src/renderer/src/pages/securityLocale.ts` 的 `ruleGroups` 当前均为 **11 项**。用户已确认沿用现有 11 项，不新增规则。
- `desktop/src/renderer/src/pages/SecurityPage.tsx` 当前只选择项目；对话区绑定 `useSessionStore` 的 `activeId`，无法选其他对话。项目和对话都可展开 `PolicyEditor`，即使本层未保存自定义也能编辑规则；选择全局“自定义”时还会在打开编辑器前立即保存一份规则。保存函数通过对象展开合并旧字段，需防止切换层级或方案时留下旧规则。
- `desktop/src/renderer/src/components/PermissionSelector.tsx` 使用同一后端方案定义显示芯片，但点击“自定义”会立即把当前生效规则写入对话；还有“设为全局默认”快捷操作，和本轮的草稿保存、全局只在默认权限页修改要求不符。“设为项目默认”现从有效 `mode` 和 `rules` 构建方案，需核对继承、自定义及目标项目归属。
- `channel/desktop/desktop_channel.py` 的会话设置响应与 `agent/permission/center.py` 的安全中心响应分别计算生效方案。前端 `sessionSettingsStore.ts` 缓存输入框状态，安全页保存后需要让目标对话的芯片重新读取；查看非当前对话时要用所选对话的真实项目关联，不把当前项目选择当成其归属。
- `extra_roots` 存在同一 `security_policy` 对象中。当前“恢复继承”若把整个对话策略清空，可能连目录授权一起删掉；而仅保存目录也会让该层对象非空，不能因此误认为本层保存了权限方案。目录管理应独立于方案展示、继承和复制。
- 相关基础测试位于 `tests/test_security_center.py`；新增测试需分别覆盖预设覆盖、自定义草稿不落盘、项目/对话选择与归属、跨入口同步、旧部分规则记录和目录授权独立性。
