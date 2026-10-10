# Stella 多 Agent 审核报告

状态：进行中。修复已落地，独立复审和修复后的完整门禁都还没有做。不能视为 PASS。

## 范围

- 审核对象：本地 `develop` 在 `94f176d0` 的完整工作树。
- 审核分支：`codex/multi-agent-review-20261011`。
- 未提交改动：启动时无。
- 不包含：推送、发布、更新 `main`、真实用户数据或外部账号操作。

## 分工

| 角色 | 职责 |
| --- | --- |
| 主 Agent | 基线、门禁、去重、记录、循环推进、本地合并 |
| Agent 1 | 代码与架构 |
| Agent 2 | 安全与性能 |
| Agent 3 | 可靠性与独立评审，唯一 PASS／FAIL 判定者 |
| Agent 4 | 复现与修复 |

过程记录：`.agents/CODE_REVIEW_PROCESS.md`。

## 覆盖矩阵

| 领域 | 状态 | 证据 |
| --- | --- | --- |
| 代码质量与潜在 Bug | 审核中 | 待 Agent 1 与完整门禁 |
| 项目架构及模块依赖 | 审核中 | `docs/architecture/overview.md`；待 Agent 1 |
| 前后端功能完整性 | 审核中 | 待 Agent 1 与 UI 门禁 |
| Agent 工具调用和执行可靠性 | 审核中 | 待 Agent 2 |
| 数据库一致性与并发安全 | 审核中 | 待 Agent 3 |
| 权限控制和安全漏洞 | 审核中 | 待 Agent 2 |
| UI 交互与用户体验 | 审核中 | 待 UI 门禁与抽查 |
| 性能与资源占用 | 审核中 | 待 Agent 2 |
| 异常恢复与系统稳定性 | 审核中 | 待 Agent 3 |
| 核心业务流程及回归测试 | 审核中 | 待完整门禁 |

## 自动化证据

`.venv/bin/python scripts/quality_check.py full` 在 `94f176d0` 的退出码是 1。

| 检查 | 状态 |
| --- | --- |
| ruff | 基线 FAIL，394 条。修复后对门禁目录再跑 `ruff check` 为 0 条。完整 `quality_check.py full` 尚未重跑。 |
| pytest | PASS，1520 passed，4 skipped |
| eslint | PASS |
| build | PASS |
| typecheck | PASS |
| node | PASS |
| ui | PASS |
| policy | PASS |

草稿 `audit-reports/Full-Audit-2026-10-11.md` 只记录自动化结果。

## 已确认问题

首轮编号已经去重。下面的修复由主 Agent 落地，Agent 3 还没有复审，所以这些条目都还没关闭。

| 编号 | 严重程度 | 证据状态 | 摘要 |
| --- | --- | --- | --- |
| CR-001 | Critical | 已修复，待复审 | 桌面「等待客户端确认通知」记为完成；其他 waiting 可重试，不再停用任务 |
| CR-002 | High | 已修复，待复审 | 桌面通知正文写入投递记录，进程重启后可按等待中的记录再领取 |
| CR-003 | High | 已修复，待复审 | 空的桌面接收人归一成 `desktop`；任务和待办界面也提交这个值 |
| CR-004 | Medium | 已修复，待复审 | 新建通知任务如果渠道仍是占位项，保存会被拦住。已有的 web 会话任务保持可用 |
| CR-005 | High | 已修复，待复审 | 损坏的 `tasks.json` 会抛出错误，文件内容保持原样 |
| CR-006 | High | 已修复，待复审 | 记账和月报、年报放进同一个事务，年报明细失败时整笔回滚 |
| CR-007 | High | 已修复，待复审 | 日历投影抛错时不写确认时间，outbox 保持未确认 |
| CR-008 | Medium | 建议排除，待 Agent 3 接受 | 待办提醒租约过期后再次领取是现有测试要求的至少一次投递，这次不改行为 |
| CR-009 | Medium | 已修复，待复审 | 同一个 TodoService 在锁释放后的下一次读取会重试日历迁移 |
| CR-010 | High | 已修复，待复审 | `mailbox.json` 进入凭据路径、沙箱保护和命令拦截 |
| CR-011 | High | 已修复，待复审 | 微信凭据文件进入沙箱保护列表，拼接命令也不能从沙箱里读到原文件 |
| CR-012 | High | 已修复，待复审 | 浏览器拒绝 IPv4 映射后的链路本地地址；普通 IPv4 地址在 Python 3.9 上不再误伤 |
| CR-013 | Medium | 已修复，待复审 | `python -c` 里的 urllib/requests 和 `npm i` 计入拒绝规则；网络拒绝同时写入 Seatbelt 和 bubblewrap |
| CR-014 | Medium | 已修复，待复审 | 仍在运行的后台命令计入 20 个上限 |
| CR-015 | High | 已补代码，待复审 | Linux 沙箱参数增加 `--unshare-pid`。本机是 macOS，只验证了生成的参数，没有实际跑 bubblewrap |
| CR-016 | Low | 已修复，待复审 | 简报和日程的滚动标记改到真正滚动的主区域。还没有做浏览器交互验证 |
| CR-017 | Medium | 已修复，待复审 | 七个模型适配器先保存异常文本，再交给稍后执行的生成器 |
| CR-018 | Medium | 已修复，待复审 | 门禁目录的 ruff 从 394 条降到 0。含 Python 3.9 目标版本、显式导入、未使用符号和三份重复的 ` 2.py` 文件 |

## 未覆盖与限制

外部渠道的真实发送、Apple 本机权限弹窗、需要登录的第三方服务，不能在隔离环境端到端执行。这些限制不自动构成缺陷，也不构成 PASS。
