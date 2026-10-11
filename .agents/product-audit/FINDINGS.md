# Stella 产品问题清单

更新日期：2026-10-12。代码基线：`af8ba5b2`。本次整理报告并核对关键代码，业务代码尚未修复。

## 如何阅读与核验

- **待修复**：存在具体实现差距，进入修复清单。当前共 19 项。
- **设计建议**：需要确定产品方案，当前共 3 项（PD-17、PD-20、PD-21）。
- **已修复**：需要代码修改及验收证据；当前 0 项。
- 代码证据证明对应分支存在；上轮模拟界面测试只证明替身数据下的交互。本次没有重新运行应用。
- 每条“核验步骤”是下一次验证时的操作说明，不代表本次已执行。待验证的具体部分写在该条“证据边界”中。

五条原则：①管理位置明确；②实际结果及来源清楚；③选择的影响范围明确；④复用已有规则；⑤布局服务内容。

## 按问题查找

| 编号 | 当前结论 | 问题或待决定事项 | 优先级 | 修复任务 |
| --- | --- | --- | --- | --- |
| [PD-01](#pd-01) | 待修复 | 安全中心把固定目录当作真实连接 | P0 | T-01 |
| [PD-02](#pd-02) | 待修复 | 选择自定义会提前保存；改任务渠道会清除执行对话 | P0 | T-01 |
| [PD-03](#pd-03) | 待修复 | 安全总览说明没有解释当前状态 | P1 | T-01 |
| [PD-04](#pd-04) | 待修复 | 安全活动的工具名称映射不完整 | P1 | T-01 |
| [PD-05](#pd-05) | 待修复 | 安全中心重复录入凭据，清单遗漏自定义厂商 | P1 | T-01 |
| [PD-06](#pd-06) | 待修复 | 渠道页把已启用显示为已连接 | P1 | T-02 |
| [PD-07](#pd-07) | 待修复 | 部分设置保存后，当前运行仍使用其他配置 | P1 | T-03 |
| [PD-08](#pd-08) | 待修复 | 每日记忆蒸馏要求进程中仍有 Agent 实例 | P1 | T-04 |
| [PD-09](#pd-09) | 待修复 | 错过任务缺少结果记录；停用原因只能主动进入查看 | P1 | T-05 |
| [PD-10](#pd-10) | 待修复 | 账单、知识库和记忆把加载失败显示为空数据 | P1 | T-05 |
| [PD-11](#pd-11) | 待修复 | 简报生成失败后的重试按钮只刷新列表 | P1 | T-05 |
| [PD-12](#pd-12) | 待修复 | 对话受阻后缺少直接处理当前问题的入口 | P1 | T-06 |
| [PD-13](#pd-13) | 待修复 | 简报没有直达已创建对象的链接，也没展示单项失败回执 | P1 | T-07 |
| [PD-14](#pd-14) | 待修复 | 跳过模型引导后，对话缺少补齐配置的直接入口 | P1 | T-08 |
| [PD-15](#pd-15) | 待修复 | 桌面浏览器安装文档缺少可执行的步骤 | P2 | T-09 |
| [PD-16](#pd-16) | 待修复 | Apple 设置可同时显示已连接和权限被拒绝 | P2 | T-02 |
| [PD-17](#pd-17) | 设计建议 | 连接、项目等名称是否需要进一步区分 | 未排期 | T-10 |
| [PD-18](#pd-18) | 待修复 | 日志断流后仍显示实时 | P3 | T-10 |
| [PD-19](#pd-19) | 待修复 | 首次打开简报、知识库和任务时缺少明确下一步 | P2 | T-10 |
| [PD-20](#pd-20) | 设计建议 | 两个通知选择器是否需要合成共享控件 | 未排期 | T-11 |
| [PD-21](#pd-21) | 设计建议 | 是否增加跨页面的待处理汇总 | 未排期 | T-12 |
| [PD-22](#pd-22) | 待修复 | 后端端口错误在中文界面仍显示英文 | P3 | T-10 |

<a id="pd-01"></a>

## PD-01 安全中心把固定目录当作真实连接

**待修复 · P0 · 原则 1、2 · T-01**

- **在哪里：** 安全中心 → 外部连接、总览。
- **现在的问题：** 浏览器固定显示已连接；邮箱和日历分别读取通用密码、令牌字段，而不是简报邮箱配置与 Apple 授权。总览将这些条目计入可用连接。用户配好服务后，两处状态仍可能相反。
- **核验步骤：** 使用未配置外部服务的隔离环境打开连接页，检查浏览器及可用数量；再配置简报邮箱或 Apple 日历，对照设置页与安全页。
- **修复后应看到／待决定：** 连接条目、管理入口和数量读取实际服务状态；只有已验证且允许使用的实例计入可用数量。空范围显示未声明，服务授权范围与权限规则分别解释。
- **依据：** [center.py](/Users/starpickerr/Desktop/Codes/Stella/agent/permission/center.py:115)；[gateway.py](/Users/starpickerr/Desktop/Codes/Stella/agent/permission/gateway.py:503)；[SecurityPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/SecurityPage.tsx:594)。
- **证据边界：** 本次代码复核确认。真实连接及撤销后的界面未运行验证。空范围缺少附加范围限制，不等于绕过全部权限规则。

<a id="pd-02"></a>

## PD-02 选择自定义会提前保存；改任务渠道会清除执行对话

**待修复 · P0 · 原则 2、3、4 · T-01**

- **在哪里：** 安全中心 → 默认权限；定时任务 → 编辑。
- **现在的问题：** ① 从预设点自定义时，界面立即提交全局 custom，尚未点保存自定义。② 任务卡片仅写沿用绑定对话，缺少实际方案及来源。③ 任务从 web 渠道改到其他渠道时，前后端都清除绑定对话等字段。
- **核验步骤：** 先选预设，再点自定义但不保存，刷新检查方案；编辑已有 web 任务并切换 Telegram，保存后检查绑定字段；查看沿用卡片是否显示实际方案和来源。三项分别核验。
- **修复后应看到／待决定：** 自定义仅在明确保存后生效；执行对话与发送渠道分别保存；有效绑定时显示沿用的方案及来源。未绑定任务明确选择运行预设。
- **依据：** [SecurityPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/SecurityPage.tsx:440)；[TasksPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/TasksPage.tsx:284)；[mutations.py](/Users/starpickerr/Desktop/Codes/Stella/agent/scheduler/mutations.py:61)；[conversation.py](/Users/starpickerr/Desktop/Codes/Stella/agent/scheduler/conversation.py:89)；[tool_invocation.py](/Users/starpickerr/Desktop/Codes/Stella/agent/runtime/tool_invocation.py:102)。
- **证据边界：** 本次代码复核确认；上轮模拟界面测试也记录了提前提交与沿用文案。有效绑定的执行路径已经会读取对话权限，本条并非“完全没有权限继承”。

<a id="pd-03"></a>

## PD-03 安全总览说明没有解释当前状态

**待修复 · P1 · 原则 2 · T-01**

- **在哪里：** 安全中心 → 总览。
- **现在的问题：** 状态标题下固定展示进程隔离原因。正常、待审批或拦截时，用户看到的说明仍可能是同一段沙箱信息，且包含后端英文原文。
- **核验步骤：** 分别准备无待处理、有待审批、有近期拦截的状态，检查标题下的说明是否解释对应状态，再切换界面语言。
- **修复后应看到／待决定：** 状态说明解释当前原因并指向对应记录；进程隔离作为独立信息展示，两部分随语言切换。
- **依据：** [SecurityPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/SecurityPage.tsx:329)；[center.py](/Users/starpickerr/Desktop/Codes/Stella/agent/permission/center.py:168)。
- **证据边界：** 代码证据来自上轮；本次未重跑这三种状态。

<a id="pd-04"></a>

## PD-04 安全活动的工具名称映射不完整

**待修复 · P1 · 原则 4 · T-01**

- **在哪里：** 安全中心 → 安全活动、过滤器；对话审批弹窗。
- **现在的问题：** 安全页维护约 11 项工具翻译，表外工具回退到原始 id；审批弹窗直接显示 id。完整目录已有双语名称，当前各入口使用的数据不同。
- **核验步骤：** 准备 todos、scheduler 和未知工具的活动记录，对照中文与英文活动列表、过滤器及审批弹窗。
- **修复后应看到／待决定：** 安全活动及审批读取同一完整工具目录；名称随语言变化，过滤仍按稳定 id。能力页标题继续使用用户指定的调用名。
- **依据：** [securityLocale.ts](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/securityLocale.ts:235)；[catalog.py](/Users/starpickerr/Desktop/Codes/Stella/agent/tools/catalog.py:1)；[ChatApprovalDialog.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/components/ChatApprovalDialog.tsx:48)。
- **证据边界：** 本次核对翻译表与审批展示。旧报告“安全活动与能力页同名”的验收已纠正：两处标题用途不同。

<a id="pd-05"></a>

## PD-05 安全中心重复录入凭据，清单遗漏自定义厂商

**待修复 · P1 · 原则 1、4 · T-01**

- **在哪里：** 设置 → 模型；安全中心 → 凭据。
- **现在的问题：** 安全中心仍有厂商下拉、密钥录入和访问密码卡片。清单只遍历顶层配置与环境变量名，遗漏嵌套自定义厂商；环境变量值为空也可能被列为已配置。
- **核验步骤：** 保存一个自定义厂商测试密钥，并准备一项空的 API_KEY 环境变量，刷新清单。删除测试凭据后再检查模型设置与重启后的状态。
- **修复后应看到／待决定：** 安全总览仅展示实际非空凭据及来源并提供确认删除；模型页负责新增修改，通用页负责访问密码。跨入口状态一致。
- **依据：** [center.py](/Users/starpickerr/Desktop/Codes/Stella/agent/permission/center.py:53)；[center.py](/Users/starpickerr/Desktop/Codes/Stella/agent/permission/center.py:73)；[securityLocale.ts](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/securityLocale.ts:9)。
- **证据边界：** 本次代码复核确认清单扫描方式。删除多来源凭据的完整运行效果仍需按需求验证。

<a id="pd-06"></a>

## PD-06 渠道页把已启用显示为已连接

**待修复 · P1 · 原则 2 · T-02**

- **在哪里：** 渠道 → Telegram、飞书等渠道卡片。
- **现在的问题：** 列表 active 来自配置名单。连接操作先写名单，再启动后台进程；启动失败或管理器缺失时，名单仍保留。除微信专有登录状态外，页面据 active 显示已连接。
- **核验步骤：** 在测试环境令渠道启动失败，刷新或重新进入渠道页，检查卡片是否仍显示已连接，以及失败原因是否仍能看到。
- **修复后应看到／待决定：** 分别展示配置启用、启动中、连接成功及失败；列表读取运行状态，失败原因可在重新进入后查看。
- **依据：** [desktop_channel.py](/Users/starpickerr/Desktop/Codes/Stella/channel/desktop/desktop_channel.py:5054)；[desktop_channel.py](/Users/starpickerr/Desktop/Codes/Stella/channel/desktop/desktop_channel.py:5107)；[desktop_channel.py](/Users/starpickerr/Desktop/Codes/Stella/channel/desktop/desktop_channel.py:5229)；[ChannelsPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/ChannelsPage.tsx:32)。
- **证据边界：** 本次代码复核确认。未用真实渠道令牌验证启动与断线。投递目录是否可发送，应单独核对其 ready 来源。

<a id="pd-07"></a>

## PD-07 部分设置保存后，当前运行仍使用其他配置

**待修复 · P1 · 原则 2 · T-03**

- **在哪里：** 模型设置的向量模型与搜索；助手设置的深度思考。
- **现在的问题：** ① 向量配置保存后，运行中的记忆对象等重建才切换。② 固定搜索服务缺密钥时回退到另一已配置服务。③ thinking-only 模型会强制开启思考。保存值与实际运行值可能不同。
- **核验步骤：** 分别修改向量模型并在重建前后检索；固定一个缺密钥的搜索服务后查看实际调用；在 thinking-only 模型关闭思考后检查请求参数。
- **修复后应看到／待决定：** 分别说明保存状态、当前运行配置及切换条件；索引提供明确重建入口，搜索标出实际服务，思考设置说明模型限制。
- **依据：** [desktop_channel.py](/Users/starpickerr/Desktop/Codes/Stella/channel/desktop/desktop_channel.py:4832)；[web_search.py](/Users/starpickerr/Desktop/Codes/Stella/agent/tools/web_search/web_search.py:161)；[agent_bridge.py](/Users/starpickerr/Desktop/Codes/Stella/bridge/agent_bridge.py:274)。
- **证据边界：** 本次代码复核确认三条执行分支。真实请求、检索结果及向量设置提示的完整呈现待验证；不能概括为“所有设置都没有生效提示”。

<a id="pd-08"></a>

## PD-08 每日记忆蒸馏要求进程中仍有 Agent 实例

**待修复 · P1 · 原则 2 · T-04**

- **在哪里：** 每日记忆作业；助手设置 → 自进化。
- **现在的问题：** 每日冲洗函数在存活 Agent 列表为空时直接返回，后面的蒸馏也随之跳过。自进化轮次及最后活跃时间存放在实例内。文档中的每日承诺未说明这些运行条件。
- **核验步骤：** 保留当天的测试记忆，重启后不建立 Agent 实例，触发每日作业并检查产物；另检查自进化重启后的轮次与资格。
- **修复后应看到／待决定：** 每日作业的条件与文档一致，结果或跳过原因可查。自进化是否跨重启继续积累资格，需单独确定；界面先准确说明现有条件。
- **依据：** [agent_initializer.py](/Users/starpickerr/Desktop/Codes/Stella/bridge/agent_initializer.py:714)；[trigger.py](/Users/starpickerr/Desktop/Codes/Stella/agent/evolution/trigger.py:60)；[features.mdx](/Users/starpickerr/Desktop/Codes/Stella/docs/intro/features.mdx:12)。
- **证据边界：** 本次代码复核确认依赖实例。关闭可见对话页不等于实例被销毁；应用退出时也无法执行作业。旧报告混用这些条件，现已分开。

<a id="pd-09"></a>

## PD-09 错过任务缺少结果记录；停用原因只能主动进入查看

**待修复 · P1 · 原则 2 · T-05**

- **在哪里：** 定时任务卡片与调度记录。
- **现在的问题：** 任务逾期超过 600 秒时，重复任务推进下次时间，一次性任务过期停用，均未写入本次跳过结果。不可重试失败会停用并保存错误；卡片能显示已保存的错误，但该停用分支没有发出新的失败通知。
- **核验步骤：** 准备逾期超过 10 分钟的重复及一次性任务，检查结果字段和卡片；再触发不可重试失败，对照停用、错误及投递记录。
- **修复后应看到／待决定：** 错过和失败各有准确结果记录。对已设置通知目的地的任务，建议复用该目的地提示失败，并链接任务详情。
- **依据：** [service.py](/Users/starpickerr/Desktop/Codes/Stella/agent/scheduler/service.py:129)；[service.py](/Users/starpickerr/Desktop/Codes/Stella/agent/scheduler/service.py:270)；[ui_tasks.py](/Users/starpickerr/Desktop/Codes/Stella/tests/ui_tasks.py:117)。
- **证据边界：** 本次代码复核确认；上轮模拟测试确认卡片能显示失败句。实际系统通知未验证；通知机制属于修复方案建议。

<a id="pd-10"></a>

## PD-10 账单、知识库和记忆把加载失败显示为空数据

**待修复 · P1 · 原则 2 · T-05**

- **在哪里：** 账单周期列表；知识库；记忆文件列表。
- **现在的问题：** 账单请求失败后设置空数组；知识库首次加载失败后 data 保持空；记忆失败后清空列表。这些状态进入无数据引导，用户难以区分故障与真正没有内容。
- **核验步骤：** 分别令三个列表接口返回错误或断开连接，再恢复接口并重新加载。检查失败时的提示、重试入口及恢复后的原数据。
- **修复后应看到／待决定：** 加载失败显示原因与重试；成功且零条数据才显示入门引导。日历已有独立错误条，Apple 授权说明另按 PD-16 核验。
- **依据：** [PeriodList.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/bills/PeriodList.tsx:36)；[KnowledgePage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/KnowledgePage.tsx:232)；[MemoryPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/MemoryPage.tsx:57)。
- **证据边界：** 本次代码复核确认。日历的空本地日程不能直接证明 Apple 授权有问题，已从本条确定结论中移出。

<a id="pd-11"></a>

## PD-11 简报生成失败后的重试按钮只刷新列表

**待修复 · P1 · 原则 2 · T-05**

- **在哪里：** 简报 → 页面顶部错误条。
- **现在的问题：** 错误条的重试调用加载列表和来源，没有调用生成函数。用户再次生成的意图没有执行。持久化简报错误已经可在详情中显示，不能说失败记录全部丢失。
- **核验步骤：** 模拟一次生成失败，点击顶部重试，查看是否发送生成请求；重新进入失败简报，检查详情错误是否仍在。
- **修复后应看到／待决定：** 生成失败的主动作重新生成；列表加载失败的主动作重新加载。失败时保留旧内容和已保存的失败原因。
- **依据：** [BriefingPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/BriefingPage.tsx:142)；[BriefingPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/BriefingPage.tsx:187)；[BriefingDetail.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/briefing/BriefingDetail.tsx:53)。
- **证据边界：** 本次代码复核确认按钮与详情渲染。真实生成重试尚未运行；旧报告关于错误全部在内存中的说法已纠正。

<a id="pd-12"></a>

## PD-12 对话受阻后缺少直接处理当前问题的入口

**待修复 · P1 · 原则 1、2 · T-06**

- **在哪里：** 对话中的权限拒绝、结果未知条及审批。
- **现在的问题：** 权限拒绝只链接安全活动；结果未知只提供复制用户原话；审批弹窗只在当前流式对话中显示。切到其他页面后缺少导航提醒。停止对话会取消待确认，取消路径本身已有实现。
- **核验步骤：** 分别触发权限拒绝、结果未知和待审批；检查能否进入该对话权限或相关业务对象；切页查找同一审批，再停止并核对取消状态。
- **修复后应看到／待决定：** 拒绝提示进入准确的权限对象；未知结果引导核对相关业务记录；跨页仍能找到待审批。具体重试与提醒形式按已有机制落实。
- **依据：** [MessageSteps.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/components/MessageSteps.tsx:157)；[ChatPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/ChatPage.tsx:326)；[ChatApprovalDialog.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/components/ChatApprovalDialog.tsx:42)；[gateway.py](/Users/starpickerr/Desktop/Codes/Stella/agent/permission/gateway.py:657)。
- **证据边界：** 本次代码复核确认组件及取消分支。多页面切换和写入结果核对待运行验证；原步骤重试需验证请求仍可恢复。

<a id="pd-13"></a>

## PD-13 简报没有直达已创建对象的链接，也没展示单项失败回执

**待修复 · P1 · 原则 1、2 · T-07**

- **在哪里：** 简报 → 信息列表及单条内容。
- **现在的问题：** 列表只用文字标记已关联事务，缺少直达对象的动作；列表没有呈现失败、冲突或删除状态。后台已经保存行动状态和错误，并在详情数据中返回，因此缺口主要在界面展示与恢复操作。
- **核验步骤：** 从简报创建一个事务，再让另一项写入失败，刷新页面。对照返回数据中的回执与界面，并检查能否打开成功创建的对象及重试失败项。
- **修复后应看到／待决定：** 复用现有行动回执显示单项结果，成功可进入对应对象，失败可定位原因和重试。重复操作遵守现有稳定业务键。
- **依据：** [ItemList.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/briefing/ItemList.tsx:170)；[actions.py](/Users/starpickerr/Desktop/Codes/Stella/agent/briefing/actions.py:229)；[actions.py](/Users/starpickerr/Desktop/Codes/Stella/agent/briefing/actions.py:433)。
- **证据边界：** 本次代码复核确认回执已持久化。旧报告“失败只存在页面内存”已撤回。定时任务的关联事务按钮属于另一条已可用路径。

<a id="pd-14"></a>

## PD-14 跳过模型引导后，对话缺少补齐配置的直接入口

**待修复 · P1 · 原则 1 · T-08**

- **在哪里：** 首次引导 → 跳过 → 对话。
- **现在的问题：** 跳过状态只作用于当前应用进程。对话欢迎区与发送错误未提供缺密钥时进入模型设置的直接动作，用户需要自行从侧栏寻找。
- **核验步骤：** 使用需要密钥且未配置的测试模型，跳过引导后发送消息，检查提示和设置入口；补齐后回原对话发送。
- **修复后应看到／待决定：** 识别当前模型缺少必要配置，给出可读原因及模型设置入口；配置后回原对话继续。
- **依据：** [onboardingStore.ts](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/store/onboardingStore.ts:3)；[OnboardingWizard.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/components/OnboardingWizard.tsx:131)；[ChatPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/ChatPage.tsx:30)。
- **证据边界：** 代码路径及上轮证据支持入口缺口，本次未重跑首次引导。适用前提是当前模型需要密钥，不能泛化到所有本地模型。

<a id="pd-15"></a>

## PD-15 桌面浏览器安装文档缺少可执行的步骤

**待修复 · P2 · 原则 1、2 · T-09**

- **在哪里：** 功能介绍 → Browser；能力页已确定的展示设计。
- **现在的问题：** 功能介绍写 stella install-browser 后接 for desktop use，但后面没有桌面步骤；桌面工具错误提示使用对话命令 /install-browser。读文档的桌面用户无法按该段完成安装。
- **核验步骤：** 阅读 Browser 段落，核对桌面提示中的安装动作；在隔离桌面环境检查 /install-browser 能否启动安装。
- **修复后应看到／待决定：** 分别写清终端安装和桌面对话安装入口。能力页继续使用工具调用名、状态开关、完整介绍和就地展开。
- **依据：** [features.mdx](/Users/starpickerr/Desktop/Codes/Stella/docs/intro/features.mdx:75)；[browser_tool.py](/Users/starpickerr/Desktop/Codes/Stella/agent/tools/browser/browser_tool.py:264)；[SkillsPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/SkillsPage.tsx:123)；[ui_capabilities.py](/Users/starpickerr/Desktop/Codes/Stella/tests/ui_capabilities.py:82)。
- **证据边界：** 本次代码与文档复核确认安装入口缺口。工具名和状态开关符合用户既定设计，原报告将其列为强制修改项的结论已撤回。

<a id="pd-16"></a>

## PD-16 Apple 设置可同时显示已连接和权限被拒绝

**待修复 · P2 · 原则 2 · T-02**

- **在哪里：** 设置 → 连接 → Apple 日历、提醒事项。
- **现在的问题：** connected 表示曾保存连接配置，授权状态另从系统读取。界面可组合出已连接 · 权限：denied，并直接展示其他英文枚举。
- **核验步骤：** 在测试环境模拟已保存配置但授权 denied，再重新检查并切换语言；与安全中心相同服务状态对照。
- **修复后应看到／待决定：** 分别表达已配置、当前授权和是否可同步；授权状态用当前语言说明下一步；安全中心读取同一事实。
- **依据：** [apple_sync.py](/Users/starpickerr/Desktop/Codes/Stella/agent/calendar/apple_sync.py:155)；[AppleIntegrations.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/settings/AppleIntegrations.tsx:156)。
- **证据边界：** 本次代码复核确认。真实系统授权收回与重新授权未运行验证。

<a id="pd-17"></a>

## PD-17 连接、项目等名称是否需要进一步区分

**设计建议 · 未排期 · 原则 1、4 · T-10**

- **在哪里：** 设置、渠道、安全中心；事务分组与文件夹项目。
- **现在的问题：** 多个入口使用相近的连接或项目名称，管理对象不同。名称相近是事实，现有证据没有证明用户一定混淆。原报告把混淆场景直接当成已确认缺陷，证据不足。
- **核验步骤：** 按管理邮箱、Apple 集成、消息渠道、事务分组、文件夹权限等目标，请使用者指出入口并完成操作，记录误入位置与原因。
- **修复后应看到／待决定：** 待决定：是否调整展示名或增加说明。已有六类设置结构继续作为基线，具体名称在验证后确定。
- **依据：** [SettingsPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/SettingsPage.tsx:1)；[TodosPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/TodosPage.tsx:1)；[NavRail.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/layout/NavRail.tsx:42)。
- **证据边界：** 名称差异可由代码核对；是否造成实际困扰待使用验证。此条单独列为设计建议。

<a id="pd-18"></a>

## PD-18 日志断流后仍显示实时

**待修复 · P3 · 原则 2 · T-10**

- **在哪里：** 日志 → 顶部绿点与实时文字。
- **现在的问题：** 绿点和实时文字固定渲染；日志流只处理消息，没有将连接中或错误状态接到指示器。连接中断后页面仍可能显示实时。
- **核验步骤：** 打开日志时延迟流连接，再断开流，检查指示器是否随连接状态变化。
- **修复后应看到／待决定：** 指示器读取流状态，区分连接中、实时和已断开；提供可发现的恢复动作。
- **依据：** [LogsPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/LogsPage.tsx:17)；[LogsPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/LogsPage.tsx:116)。
- **证据边界：** 本次代码复核确认。断流界面未运行验证。

<a id="pd-19"></a>

## PD-19 首次打开简报、知识库和任务时缺少明确下一步

**待修复 · P2 · 原则 1、5 · T-10**

- **在哪里：** 简报无来源；知识库零文档；定时任务频率与通知选择。
- **现在的问题：** 简报无来源时生成按钮禁用，空内容区仍要求选择简报；知识库空分支只有去对话，已实现的新建和导入入口在该分支外。任务显示 cron、英文时间单位或投递原始状态；无可用渠道提示只是一句文字。
- **核验步骤：** 用零来源、零文档、零可用通知渠道的测试数据分别进入页面，检查是否能从当页完成配置或创建；查看任务频率及投递状态是否可读。
- **修复后应看到／待决定：** 空页面提供到达现有设置、创建或渠道管理的动作；任务频率和投递结果使用可理解的说明。
- **依据：** [BriefingPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/BriefingPage.tsx:181)；[KnowledgePage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/KnowledgePage.tsx:407)；[TasksPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/TasksPage.tsx:25)；[TasksPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/TasksPage.tsx:591)。
- **证据边界：** 本次代码复核确认这些分支。具体首要动作和自然语言频率展示形式属于实施设计。

<a id="pd-20"></a>

## PD-20 两个通知选择器是否需要合成共享控件

**设计建议 · 未排期 · 原则 4 · T-11**

- **在哪里：** 事务 → 提醒设置；定时任务 → 通知设置。
- **现在的问题：** 两处分别渲染选择器，但已经读取共享目的地目录，并过滤相同的主动渠道。重复控件本身不证明业务规则不同。任务的旧飞书字段仍可见于遗留记录，新保存已有渠道校验。
- **核验步骤：** 使用同一份目的地数据，对照选项、空状态、接收人和测试发送；用旧飞书任务检查提示与保存结果。
- **修复后应看到／待决定：** 待决定：是否抽取共享控件，降低后续维护成本。若发现选项或校验实际不一致，再补具体缺陷证据。
- **依据：** [TasksPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/TasksPage.tsx:534)；[TodosPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/TodosPage.tsx:1185)；[taskChannel.ts](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/taskChannel.ts:1)。
- **证据边界：** 本次代码复核确认共享目录和独立控件。现有证据不足以认定出现了两套投递业务规则。

<a id="pd-21"></a>

## PD-21 是否增加跨页面的待处理汇总

**设计建议 · 未排期 · 原则 1、4 · T-12**

- **在哪里：** 安全审批、对话未知结果、简报行动等记录。
- **现在的问题：** 各类待处理在各自页面查看，导航没有统一数量。统一收件箱是一个可能的设计方案；现有五条原则没有规定必须采用它。
- **核验步骤：** 同时准备审批、结果未知和简报失败，记录用户能否发现并分别处理，以及跨页寻找的负担。
- **修复后应看到／待决定：** 待决定：是否增加只读汇总或导航提醒。处理动作继续使用各业务记录的原接口。
- **依据：** [NavRail.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/layout/NavRail.tsx:42)；[ChatApprovalDialog.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/components/ChatApprovalDialog.tsx:42)；[ChatPage.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/pages/ChatPage.tsx:326)。
- **证据边界：** 当前入口分散可核对；汇总的必要性和形式需要产品决定。

<a id="pd-22"></a>

## PD-22 后端端口错误在中文界面仍显示英文

**待修复 · P3 · 原则 5 · T-10**

- **在哪里：** 桌面启动失败状态页。
- **现在的问题：** 端口解析超时、非法端口或 IPC 拒绝写入英文错误句，状态页把该句原样展示。中文用户能重试，但具体原因仍是英文。
- **核验步骤：** 分别模拟端口超时、非法值和 IPC 拒绝，检查中文状态页错误、重试与日志入口。
- **修复后应看到／待决定：** 这些错误进入现有本地化错误映射，保留重试和查看日志。
- **依据：** [useBackend.ts](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/hooks/useBackend.ts:167)；[StatusScreen.tsx](/Users/starpickerr/Desktop/Codes/Stella/desktop/src/renderer/src/components/StatusScreen.tsx:103)。
- **证据边界：** 本次代码复核确认。真实冷启动中的发生频率未测量，不能据此推断启动普遍不稳定。

## 本次纠正了哪些旧结论

| 条目 | 旧报告的误导表述 | 当前结论 |
| --- | --- | --- |
| PD-02 | 沿用没有读取绑定对话方案 | 有效绑定已有读取路径；需修复渠道清除绑定、方案展示及未绑定处理 |
| PD-04 | 安全活动必须与能力卡标题同名 | 两处共享工具身份与目录；安全活动用本地化名称，能力卡保持调用名 |
| PD-08 | 没有打开对话就不会蒸馏 | 条件是进程内没有存活 Agent 实例；可见页面与实例生命周期不同 |
| PD-09 | 失败看不见 | 已保存错误能在任务卡片显示；跳过记录与主动提醒仍有缺口 |
| PD-11 | 生成错误只保存在页面内存 | 简报详情已有持久化错误；顶部重试动作仍只刷新 |
| PD-13 | 行动失败回执未保存 | 后台已保存状态与错误；界面缺少单项呈现和恢复动作 |
| PD-15 | 工具名和状态开关是必须修复的缺陷 | 这是用户确定的展示设计；本条仅保留桌面安装文档缺口 |
| PD-17、PD-20、PD-21 | 名称相近、控件重复、入口分散均算确定缺陷 | 作为设计建议单列，先说明要决定的问题和需要的证据 |
