# Stella Full Audit — 2026-10-08

## 范围与环境

- 基线：`0c7d5576`
- 自动化检查在临时 HOME 和 STELLA_DATA_DIR 中执行；未连接真实业务数据。
- 日期：2026-10-08；分支：`feature/briefing-optimization`；开发基线：`f4131e7c`。
- 实际环境：macOS，Python 3.9.6，Node 26.8.1，pytest 8.4.2，Ruff 0.14.14，Playwright 1.52.0，TypeScript 5.9.3，ESLint 9.39.1。
- 总体自动化结果：**FAIL**，全项目 Ruff 仍有 465 项历史发现；其余已执行检查 PASS。本次全部变更的增量门禁 PASS，不能替代全项目 Ruff 的 FAIL。
- 体检保持业务代码只读；人工部分审查源码、离线复现、独立后端复查、浏览器截图。没有生产数据迁移、真实账号或外部通知发送。

## 自动化证据

| 检查 | 状态 | 命令 |
| --- | --- | --- |
| ruff | FAIL | `/Users/starpickerr/Desktop/Codes/Stella-briefing-optimization/.venv/bin/python -m ruff check --select E4,E7,E9,F agent application bridge channel cli common models scripts tests translate voice app.py config.py` |
| pytest | PASS | `/Users/starpickerr/Desktop/Codes/Stella-briefing-optimization/.venv/bin/python -m pytest tests -q` |
| eslint | PASS | `/opt/homebrew/bin/npm --prefix desktop run lint` |
| build | PASS | `/opt/homebrew/bin/npm --prefix desktop run build` |
| typecheck | PASS | `/opt/homebrew/bin/npm --prefix desktop run typecheck` |
| node | PASS | `node --experimental-strip-types --test tests/todoFocus.test.mjs` |
| ui | PASS | `/Users/starpickerr/Desktop/Codes/Stella-briefing-optimization/.venv/bin/python scripts/ui_check.py` |

## 检测范围

pytest：**1310 passed, 4 skipped, 1 warning**，36.90 秒。四个 skip 为三个 Windows 专用集成测试和一个 Python 3.9 缺少 `tomllib` 的测试；warning 为 urllib3 对 LibreSSL 2.8.3 的提示。构建退出码 0，Vite 提示部分 bundle 超过 500 kB，启动性能尚未测量。

补充检测：`npm --prefix desktop audit --omit=dev --json` 返回 **FAIL**：四个依赖节点为 Moderate，无 High/Critical，版本与开发基线一致。Playwright 使用实际 React 页面和模拟 HTTP 后端，Python handler 测试使用真实隔离 SQLite；不能将模拟交互理解成外部账号端到端成功。

| 领域 | 状态 |
| --- | --- |
| 代码质量与潜在 Bug | **历史问题确认**：465 项 Ruff 发现；模型错误生成器离线复现 NameError，见下文。变更文件 Ruff PASS。 |
| 项目架构及模块依赖 | **已审查、部分验证**：Pipeline 采集/生成、BriefingActions 决策/回执、Todo/Calendar 管业务字段、scheduler 管提醒；桌面、Application API 和 Agent 共享服务。旧 ingest 不再绕过确认创建业务。未做所有平台干净安装、循环依赖穷举。 |
| 前后端功能完整性 | **本次主流程验证**：创建/取消、失败/重试、关联/解绑、规则撤销、偏好、完整概览、日程目标跳转；HTTP handler 测试覆盖真实 SQLite 与认证先于操作。 |
| Agent 工具调用和执行可靠性 | **源码及离线验证**：BriefingTool 决策使用相同 service、失败返回 fail；运行时取消、并行调用、审批恢复测试通过。未调用付费模型测试自然语言决策。 |
| 数据库一致性与并发安全 | **关键边界验证**：加法 schema、旧键/tombstone、BEGIN IMMEDIATE、并发确认一个目标、业务提交后崩溃恢复、截止更新/移除、用户计划/完成状态保护、不可变 revision；未做生产副本迁移、多进程长期压力。 |
| 权限控制和安全漏洞 | **边界已审查、回归通过**：decide/authorize/revoke/set_preferences 为写操作，read-only Agent 不可调用；HTTP 经 `_briefing_response` 先认证。全套包含 SSRF、路径边界、Security Center、审批恢复。Electron 潜在风险单列。 |
| UI 交互与用户体验 | **简报交互验证**：实际 React 请求、反馈、搜索、偏好、范围授权；dialog 首焦点、Tab/Shift+Tab、关闭后恢复焦点通过。补充复核 900px 最小桌面窗口。390px 仅几何检查通过且拥挤，不认定手机适配 PASS。 |
| 性能与资源占用 | **有限审查**：实体/动作主键、entity-item 索引、私有 renderer 端口及进程树清理；快照反复匹配、完整概览加载全部实体需大量历史数据基准，无长期资源测量。 |
| 异常恢复与系统稳定性 | **本次故障验证**：独立 outbox ack、安全重试、scheduler 设置/取消暂时失败、崩溃后新来源冲突确认、推断会议变更确认；其他测试包含 SSE replay/cancel 与共享数据库恢复。历史模型异常缺陷保留。 |
| 核心业务流程及回归测试 | **PASS，有限制**：1310 Python 测试、桌面 lint/build/typecheck、Node、Playwright；默认建议、确认创建、提交/评分事实与完成状态分离、跨天延迟来源、历史版本、部分来源失败覆盖。外部服务/打包客户端 SKIP。 |

## 已确认问题

### 1. 历史模型异常生成器再次抛出 NameError

- 严重程度：**Medium**，已离线复现，非本次新增。
- 位置：`models/moonshot/moonshot_bot.py:319`；同类 F821 在 `models/claudeapi/claude_api_bot.py:438`、`models/deepseek/deepseek_bot.py:303`、`models/doubao/doubao_bot.py:269`、`models/linkai/link_ai_bot.py:644`、`models/mimo/mimo_bot.py:292`、`models/minimax/minimax_bot.py:294`。
- 触发/原因：请求构建失败后延迟迭代 error generator；生成器引用 `except Exception as e`，Python 离开 except 后已清理 e。
- 安全复现：临时 HOME/data 中用 `MoonshotBot.__new__` 创建无网络实例，设置 `args={'model':'kimi-k3'}`；让 `_convert_messages_to_openai_format` 抛 `RuntimeError('offline sentinel')`，调用 `call_with_tools([], stream=True)` 再 `next(result)`。
- 证据：先记录 `RuntimeError: offline sentinel`，之后输出 `NameError free variable 'e' referenced before assignment in enclosing scope`。其他六处为静态证据，未逐个运行。
- 建议：进入生成器前保存错误文本，增加各 adapter 失败回归；P1。审计未修改业务代码。

### 2. 全仓库历史静态检查未通过

- 严重程度：**Medium**；影响全项目门禁，不能标为 PASS。
- 位置：例如 `channel/chat_channel.py:8` F403、`channel/chat_channel.py:46` F405；全命令见自动化证据。
- 复现/证据：Ruff exit 1，`Found 465 errors`，152 项标记可自动修复。先前 f4131e7c 隔离审计为 492 项；相关文件清理减少 27 项。本次全部变更 Python 文件增量 Ruff PASS。
- 原因：历史通配导入、未使用变量/导入、导入顺序、未定义异常变量等；静态发现不全部等同运行时缺陷。
- 建议：先处理 F821，再分批清理历史项；不关闭规则、不批量修改无关业务，P1/P2。

### 3. 生产依赖命中 Moderate advisories

- 严重程度：**Medium**；确认锁定版本命中告警，Stella 内可利用性未复现。
- 位置：`desktop/package-lock.json` 的 `markdown-it@14.2.0`、`react-router-dom@6.30.3`，及 react-router / @remix-run/router。开发基线相同版本；新增 ESLint 未改变这些生产版本。
- 复现：`npm --prefix desktop audit --omit=dev --json`，exit 1，Moderate 4、High 0、Critical 0。
- 证据：[GHSA-253c-mchw-3w2r](https://github.com/advisories/GHSA-253c-mchw-3w2r) 描述 markdown-it 大输入 linkify 二次复杂度；`desktop/src/renderer/src/components/Markdown.tsx:19` 启用 linkify。router 告警包括 [GHSA-2j2x-hqr9-3h42](https://github.com/advisories/GHSA-2j2x-hqr9-3h42)、[GHSA-wrjc-x8rr-h8h6](https://github.com/advisories/GHSA-wrjc-x8rr-h8h6)、[GHSA-337j-9hxr-rhxg](https://github.com/advisories/GHSA-337j-9hxr-rhxg)、[GHSA-jjmj-jmhj-qwj2](https://github.com/advisories/GHSA-jjmj-jmhj-qwj2)。传递节点计数不是已验证攻击数。
- 建议：单独进行兼容性升级，受控测量超大 Markdown，检查可控 redirect/hydration 输入，P1。未运行自动 npm audit fix。

## 潜在风险

1. **Electron 权限**：`desktop/src/main/index.ts:582` 无差别批准 Chromium permission，源码确认策略宽泛；外部内容能否在该 session 请求权限未验证。使用打包应用、受控 origin、模拟设备检查来源/权限后收紧，不将源码观察当成已利用漏洞。
2. **外链和导航**：`desktop/src/main/index.ts:176` 使用 `shell.openExternal(url)`，`:184` 仅阻断不同 file URL 导航。简报来源入口仅呈现 http/https/mid；全应用仍需 Electron scheme/navigation 测试。未启动外部程序或真实敏感 URI。
3. **平台**：项目声明 Python >=3.7，开发 pytest 需要 >=3.9；历史测试部分语法不兼容 3.7。检测脚本补齐 Windows 路径、profile/temp 隔离、renderer taskkill，但未在原生 Windows 执行。
4. **历史数据量**：`agent/briefing/actions.py:112` 的快照匹配及完整概览需大量历史记录基准。并发确认测试不能替代多进程长期压力测试。
5. **390px 布局**：展开导航后正文过窄。Electron `desktop/src/main/index.ts:106` 最小宽度 900；这是未来手机/窄浏览器支持限制，本次以 900/1440 桌面窗口验收，不宣称手机布局可用。

## 未执行与限制

- **SKIP**：原生 Windows、多 Python/Node 版本、打包 Electron 权限与系统通知、生产数据库副本迁移、长期负载/内存/电池、所有屏幕完整无障碍审计。
- **SKIP**：真实 IMAP/eLearning/付费模型/渠道通知交付。已验证 scheduler 配置和恢复，不等于通知实际送达。
- **SKIP**：Semgrep、Python 依赖漏洞全扫描；选用既有安全回归、Ruff、类型检查、人工边界审查与 npm 生产依赖审计，不宣称等价覆盖。
- Skill 在本项目 `.agents/skills/`，frontmatter 自动验证；当前 Codex 会话实际发现并调用开发 Skill 和 software-audit，没有改变全局 Skill/其他项目配置。

## 交付门禁及后续优先级

- **PASS**：A 按模块检测，实际捕获并推动修复构建、认证测试隔离、崩溃恢复、推断时间确认、提醒取消重试及键盘边界，修复后重新验证；B 脚本与人工报告流程已实际执行。
- **PASS**：P0 决策授权/实体去重/用户字段保护/迁移兼容，P1 核心 UI/Agent/变化追踪有实现和回归证据。独立复查未发现仍未修复的本次新增重要后端缺陷。
- **FAIL 保留**：全项目 Ruff、npm 历史生产依赖告警。不因本次交付改为 PASS，不删除断言或关闭规则隐藏。
- 合并判断：在已验证的离线、当前平台、桌面窗口范围内，未发现本次引入的数据破坏或严重权限缺陷。历史 Medium 问题列入 P1/P2；仍需额外环境验证，此结论不是无漏洞证明。

## 失败证据

### ruff

命令：`/Users/starpickerr/Desktop/Codes/Stella-briefing-optimization/.venv/bin/python -m ruff check --select E4,E7,E9,F agent application bridge channel cli common models scripts tests translate voice app.py config.py`

```text
33 | try:
34 |     from voice.audio_convert import any_to_mp3
35 |     from pydub import AudioSegment
   |                       ^^^^^^^^^^^^
36 |     _audio_available = True
37 | except ImportError as e:
   |
help: Remove unused import: `pydub.AudioSegment`

F841 Local variable `return_file` is assigned to but never used
  --> voice/xunfei/xunfei_voice.py:86:13
   |
84 |             # Avoid the same filename under multithreading
85 |             fileName = TmpDir().path() + "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".mp3"
86 |             return_file = xunfei_tts(self.APPID,self.APIKey,self.APISecret,self.BusinessArgsTTS,text,fileName)
   |             ^^^^^^^^^^^
87 |             logger.info("[Xunfei] textToVoice text={} voice file name={}".format(text, fileName))
88 |             reply = Reply(ReplyType.VOICE, fileName)
   |
help: Remove assignment to unused variable `return_file`

F841 [*] Local variable `e` is assigned to but never used
  --> voice/xunfei/xunfei_voice.py:89:29
   |
87 |             logger.info("[Xunfei] textToVoice text={} voice file name={}".format(text, fileName))
88 |             reply = Reply(ReplyType.VOICE, fileName)
89 |         except Exception as e:
   |                             ^
90 |             logger.error("[Xunfei] textToVoice error={}".format(fileName))
91 |             reply = Reply(ReplyType.ERROR, "抱歉，讯飞语音合成失败")
   |
help: Remove assignment to unused variable `e`

Found 465 errors.
[*] 152 fixable with the `--fix` option (23 hidden fixes can be enabled with the `--unsafe-fixes` option).
```
