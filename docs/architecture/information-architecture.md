# 信息架构与配置入口

2026-10-22。用户确认职责并授权实施；本文记录当前 Desktop 实现，不是候选方案。代码入口为 `App.tsx`、`ConfigurationPages.tsx`、`NavRail.tsx` 与 `DataManagementPage.tsx`，验收入口见文末。

Stella 将信息、执行能力、模型选择与安全授权分开管理。比如用户启用 eLearning MCP 后，在数据中连接账号、选择课程和保存目录，在安全中授予课程与目录范围，简报只选择消费与整理规则。启用服务不等于获得访问权限，浏览资源不等于同步正文或放入当前模型上下文。

## 当前导航与权威表单

侧边栏信息区包括数据、知识、记忆；系统区包括模型、能力、安全、通用。其他业务入口保持各自职责。

| 入口 | 当前路由及职责 | 配置归属 |
| --- | --- | --- |
| 数据 | `/data` 默认资源浏览；`section=sources/sync/storage` 为辅助视图 | 来源启停意图、资源查询、实际支持的同步、缓存与保留状态 |
| 知识、记忆 | 原插件贡献页面 | 由业务插件维护编辑器、索引和原存储，数据仅展示引用 |
| 能力 | `/skills` 的插件、工具、技能、MCP 分页 | 安装、生命周期、运行配置；插件设置使用 `view=settings&plugin=<id>` |
| Agent 配置 | Agent 菜单进入 `/agent-settings` | 上下文、执行参数、默认行为 |
| 模型 | `/models` | 厂商地址、协议、模型目录及用途绑定 |
| 安全 | `/security` | 四种既有预设、资源与消费者授权、凭据、审批和审计 |
| 通用 | `/general`，`section=about` 滚动到关于 | 语言、外观、通知、启动、版本和更新 |

同一配置只保留一个权威编辑位置。模型内置厂商、自定义厂商、搜索服务和精简版模型页面显示凭据状态，跳转 `/security?tab=secrets&secret=<name>` 选择具体凭据。首次设置只保存模型路由，缺少凭据时继续到安全中心，不再次显示密钥输入框。自定义厂商先保存元数据，再使用 `CUSTOM:<id>` 管理密钥。Security 使用原持久化字段，不复制配置或修改厂商绑定。来源账号和认证资料仍由独立 MCP 的账号表单维护。

系统访问密码也集中在安全中心。关于区域没有独立重复表单。Apple 日历和提醒事项配置各归对应业务页 `/calendar/settings/apple`、`/todos/settings/apple`，共享底层组件并保留返回入口。

## 来源与 eLearning

`/data/sources/email` 是邮箱账号的唯一表单；`/data/sources/elearning` 是学校账号、课程选择与文件保存目录的唯一表单。简报仅保留来源消费与整理设置，并链接数据中的账号配置。能力页的 MCP 入口管理连接与启停，链接来源表单；安全页编辑原有课程、消费者和目录写权限，没有在数据页复制授权开关。

资源页支持来源、资源类型、Agent 和工作区范围，查询参数传入原生可信边界。来源跳转保留范围。正文按需读取，切换范围、刷新、读取失败或重新聚焦时清除或重新检查旧内容。来源卡片分别展示服务可用性、启停意图、授权检查与采集状态。

按来源声明显示可执行操作。邮箱采集记录保留同步、订阅、导出和 Core 本地记录清理；引用型来源不显示未实现的订阅、导出或清理。知识和记忆不复制业务编辑器。课程文件同步单独经过 Data 来源状态与所有者操作检查，使用原 MCP 下载 manifest、目录与写入授权；不覆盖用户修改过的文件，也不等同于删除上游内容。

## 兼容与失败处理

`SettingsPage.tsx` 仅承担旧 `tab/section` 链接跳转，不再承载聚合表单；模型、Agent、插件、安全、Apple、关于与数据的旧入口均跳转到对应页面。`/email`、`/elearning` 兼容跳转到来源表单并保留查询范围。配置仍使用原 API 和原存储，不清空账号、凭据、课程、会话、简报历史、游标或下载文件。

请求失败显示可重试错误；权限、来源 revision 或启停变化阻止读取结果释放。同步以已保存目录为前提，来源不可用时按钮禁用并提供数据来源入口；服务端独立复查同一条件，界面状态不构成授权。

## 验收与限制

`tests/ui_information_architecture.py`、`ui_settings_entry.py`、`ui_capabilities.py` 验证导航、唯一入口、兼容跳转和返回行为；`ui_model_selection.py` 验证六类模型用途、厂商元数据、首次设置失败重试及到安全的跳转；`ui_managed_models.py` 使用 `tests/fixtures/managed_product` 扩展构建验证精简版模型选择和凭据入口；`ui_security_modes.py` 验证四种模式、凭据选择/保存、键盘和窄窗口；`ui_data_management.py`、`ui_elearning_settings.py` 验证来源、资源筛选、正文失效、下载入口和失败反馈。

后端对应 `tests/test_security_center.py`、`test_data_api.py`、`test_data_browse_scope.py`、`test_data_elearning_resources.py` 与 `test_owned_resource_providers.py`。浏览器使用隔离的 API 数据；独立插件/MCP 的实际 RPC、授权和下载路径由上述集成测试验证，不以浏览器 Mock 代替服务验收。实际学校与邮箱账号不用于测试，OS 通知、启动项和应用更新仍由 Electron 平台适配器提供。

2026-10-22 本次代码验收：隔离 `pytest tests -q -rs` 为 **2048 PASS / 22 SKIP / 0 FAIL**；Desktop lint、typecheck、renderer/main 构建通过；上述八组浏览器脚本通过，桌面、620/640 与 390 窄窗口及英文深色凭据页面已检查。22 项跳过分别为真实外部 Agent（1）、Windows 集成（3）、工作区外开发 Skill（1）与缺少 PyInstaller 的打包用例（17）。这些跳过不代表对应平台或打包产物已验收。

独立审查发现的 HTTP 响应头等待连接泄漏、原生下载绕过来源启停及凭据表单职责问题已修复并以新增失败测试复现后验证通过；引用来源的无效订阅控件也已移除。MCP、插件和授权检查使用独立本地进程及隔离夹具，不连接真实学校或邮箱账号。
