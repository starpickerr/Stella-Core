# Stella 开发准则

本文件是 Codex 与 Cursor 的唯一开发规范入口。两边都先读这里，再进入 [`.agents/`](.agents/AGENTS.md) 管理中心：细则在 [.agents/AGENTS.md](.agents/AGENTS.md)，领域规则在 `.agents/rules/`，工作流在 [.agents/workflows/development.md](.agents/workflows/development.md)。`.agents/skills/` 里的长文只在对应 Skill 被选中时阅读，不是项目开发准则。

## 步骤

1. 查看 `git status --short --branch`、近期提交和相关代码。保留未提交改动、真实数据和已验证成果。中断后用 Git、代码和新鲜测试判断停点，不把计划或聊天记录当作完成。
2. 代码和配置修改从当前 `develop` 建立以任务命名的专用分支，分支名不以 `codex`、`cursor`、`ai` 等工具或 AI 名称开头。`main` 是正式分支。功能完成并验证后合并本地 `develop`。`develop → main`、推送远程和改写共享历史需要单独授权。
3. 范围清楚的修改直接实现。跨模块、迁移或依赖顺序不清楚时，把目标、验收和进度写进 `.agents/tasks/active/`，再按 [Skill 协作规则](.agents/rules/skill-coordination.md) 选择规划、调试或测试步骤。不要机械跑完全部 Skill。完成后把任务移到 `.agents/tasks/completed/`。
4. 先复用现有服务和接口。业务规则放在共享服务和可信边界，不在界面、Agent 和后台各写一套。
5. 改变可观察行为时，先写会失败的测试，再实现。默认门禁是 `.venv/bin/python scripts/quality_check.py incremental`。界面改动还要验证实际浏览器交互。结果分别写 PASS、FAIL、SKIP。失败先定位，不删除或放宽测试。
6. 提交遵守 [.agents/rules/git.md](.agents/rules/git.md)。不添加 `Co-authored-by`、`co-worker` 或 AI 自动署名。
7. 测试使用临时 `HOME`、`STELLA_DATA_DIR` 和工作区数据。不修改真实用户数据，不关闭权限机制来通过检查。只有用户明确说 `Full Audit` 或 `全项目体检` 时，才读取 `.agents/skills/software-audit/SKILL.md` 做只读审计。

架构入口见 [docs/architecture/overview.md](docs/architecture/overview.md)。Cursor 的常驻规则只指向本文件和 `.agents/`。Codex 的项目配置同样只指向本文件。冲突时以本文件和 `.agents/rules/` 为准。
