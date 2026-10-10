# Stella 当前迭代：开发入口

本目录是本轮需求的入口。按以下顺序阅读：

1. [需求与验收](requirements.md)：已确认的产品行为和不可破坏的边界。与旧讨论冲突时，以此文件和最新用户要求为准。
2. 对应实施计划：
   - [简报生成](../../docs/plans/active/2026-10-10-briefing-generation.md)
   - [知识库链接](../../docs/plans/active/2026-10-10-knowledge-links.md)
   - [会话安全模式](../../docs/plans/active/2026-10-10-security-modes.md)
   - [定时任务运行权限](../../docs/plans/active/2026-10-10-scheduled-task-permissions.md)
3. [讨论和日志线索](current.md)：用于追溯，不把推测当作验收结论。

建议先完成“会话安全模式”，再做依赖其预设语义的“定时任务运行权限”；“简报生成”和“知识库链接”可独立开发与验证。开始前遵循仓库根目录 `AGENTS.md`，检查 Git 状态与当前 `develop`，在专用分支实施；保留现有未提交内容。所有测试使用隔离数据。每完成一个可独立验收的计划，在对应计划里记录实际命令、PASS/FAIL/SKIP 和提交；代码与测试比计划更可信。未经用户明确要求，不合并或更新 `develop`。

本轮四项已在分支 `fix/briefing-generation-20261010` 实现并验证。最终门禁 `.venv/bin/python scripts/quality_check.py incremental`：PASS ruff、pytest（1509 passed, 4 skipped）、eslint、build、typecheck、node、ui；SKIP policy（无相关策略变更）。未经用户明确要求，不合并或更新 `develop`。工作区已有其他未提交删除记录，不能顺手提交、恢复或清理。
