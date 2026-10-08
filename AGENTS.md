# Stella 开发入口

先阅读 [.agents/AGENTS.md](.agents/AGENTS.md)，再按任务需要阅读 `.agents/rules/` 和 `.agents/skills/` 中的相关文件；不要假设嵌套目录的 `AGENTS.md` 会自动加载。

- `main` 是正式分支，`develop` 是开发基线。代码和配置修改先从当前 `develop` 创建专用分支，在分支提交并验证；用户已要求功能完成后及时合并回 `develop`。`develop → main` 仍须单独获得用户授权，禁止擅自推送或改写共享历史。
- 提交遵循 [.agents/rules/git.md](.agents/rules/git.md)，不添加 `Co-authored-by`、`co-worker` 或 AI 自动署名。
- 保护现有代码、未提交改动和真实数据。测试使用临时 `HOME`、`STELLA_DATA_DIR` 和工作区数据；审计不得接触真实数据库、凭证或外部服务。
- 默认增量门禁：`.venv/bin/python scripts/quality_check.py incremental`。UI 改动还须验证实际浏览器交互。结果分别报告 PASS、FAIL、SKIP。
- 用户明确说 `Full Audit` 或 `全项目体检` 时，读取 `.agents/skills/software-audit/SKILL.md` 并执行完整只读审计；未经明确要求不要在审计中修改业务代码。

架构与开发导航见 [docs/architecture/overview.md](docs/architecture/overview.md)；统一命令见 [docs/development/workflows.md](docs/development/workflows.md)；长期任务进度放在 `docs/plans/active/`。
