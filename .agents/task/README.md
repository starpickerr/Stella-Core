# Stella 当前迭代：开发入口

本目录是本轮需求的入口。按以下顺序阅读：

1. [需求与验收](requirements.md)：已确认的产品行为和不可破坏的边界。与旧讨论冲突时，以此文件和最新用户要求为准。
2. 对应实施计划（已完成，归档在 `docs/plans/completed/`）：
   - [简报生成](../../docs/plans/completed/2026-10-10-briefing-generation.md)
   - [知识库链接](../../docs/plans/completed/2026-10-10-knowledge-links.md)
   - [会话安全模式](../../docs/plans/completed/2026-10-10-security-modes.md)
   - [定时任务运行权限](../../docs/plans/completed/2026-10-10-scheduled-task-permissions.md)
3. [讨论和日志线索](current.md)：用于追溯，不把推测当作验收结论。

本轮四项已在分支 `fix/briefing-generation-20261010` 实现并验证，计划已从 `docs/plans/active/` 归档。最终门禁 `.venv/bin/python scripts/quality_check.py incremental`：PASS ruff、pytest（1509 passed, 4 skipped）、eslint、build、typecheck、node、ui；SKIP policy（无相关策略变更）。按用户要求合并本地 `develop`；不推送远程，也不更新 `main`。
