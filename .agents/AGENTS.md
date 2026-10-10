# Stella 开发准则细则

Codex 从仓库根目录的 `AGENTS.md` 进入本文件。Cursor 自动读取根目录 `AGENTS.md` 和 `.cursor/rules/stella-development.mdc`，并在需要领域细节时读取本文件。两边遵循同一套步骤，不另写工具专用流程。

## 执行

开始前检查分支、未提交修改、相关代码与测试。简单任务直接实施；跨模块任务写明验收标准并在 `docs/plans/active/` 记录进度。先复用现有实现，独立解决常规技术选择。中断后以 Git 状态、代码和实际测试恢复，不把计划当作完成证据。

额度耗尽、上下文压缩或工具/子代理中断时，先区分“功能未完成”和“某项审查或验证未完成”。从 `git status`、提交与合并记录、需求对应的代码/测试和新鲜检查输出判定停点；只续做缺失步骤，不因中断重做已提交且已验证的工作。复杂任务在 `docs/plans/active/` 保留可接手的进度记录；子代理失败不能算审查通过，改用可用的复核方式并如实报告。具体步骤见 [中断恢复流程](../docs/development/workflows.md#额度或上下文中断后的恢复)。

## 架构和代码

Stella 的 Agent、事务、日程、账单、简报、自动化由 Web、Desktop、Agent 工具及外部 API 共享。业务规则放在共享服务和可信边界；关注数据一致性、权限、幂等、并发、错误恢复和接口兼容。保持职责清楚，遵循 KISS、DRY、YAGNI，避免重复业务实现和无关重构。按需阅读 [架构规则](rules/architecture.md) 和 [代码导航](../docs/architecture/overview.md)。

## 调试、验证与交付

Bug 先复现并定位根因。重要行为先写能失败的测试，再实施修复。按变更范围执行 `.venv/bin/python scripts/quality_check.py incremental`；UI 用 Playwright 验证关键交互；重大改动请求代码审查。失败须分析并重跑，不删除或削弱测试。交付前检查 diff、需求和命令输出，明确 PASS、FAIL、SKIP 与限制。详见 [测试规则](rules/testing.md)。

## 安全、Git 与 UI

测试数据和凭证隔离；不要修改真实用户数据或生产环境，不通过关闭权限机制解决问题。详见 [安全规则](rules/security.md)。在专用分支完成并提交，验证后按用户当前授权合并 `develop`；`main` 和远程操作遵循 [Git 规则](rules/git.md)。UI 关注信息层级、效率、反馈、键盘可用性以及空/错/加载状态，详见 [UI 规则](rules/ui-design.md)。

## Skills

按 [Skill 协作规则](rules/skill-coordination.md) 选择规划、工作步骤和辅助 Skill；不要机械执行全部，也不要重复请求已有授权。创建项目 Skill 用 Codex 内建 `skill-creator`，产物只放本项目。Skill 不存在或不兼容时使用常规工程流程并如实说明。来源和维护细节见 [Skill 清单](../docs/development/skills.md)。

默认中文沟通。阶段性说明实质进展，最终说明改动、验证证据和剩余问题。
