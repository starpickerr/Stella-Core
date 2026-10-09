# 开发与验证工作流

## 开始与恢复

1. 在仓库根目录检查 `git status --short --branch`、近期提交和相关代码。保留所有未提交内容。
2. 从当前 `develop` 建专用分支；复杂任务在 `docs/plans/active/` 写目标、验收、决策、已完成工作和下一步。恢复时以代码和测试核实计划条目。
3. 按 [架构导航](../architecture/overview.md) 找服务入口、数据路径与对应测试；按需读取 `.agents/rules/`。
4. 功能与测试在分支提交。用户已经授权完成功能后合并本地 `develop`；发布到 `main` 或推送远程需要另行明确授权。

## 额度或上下文中断后的恢复

额度不足可能只中断代码审查或回复，并不说明功能代码、测试、提交和合并也中断。恢复时按证据逐项判定：

1. 读取最新用户要求与既有授权；运行 `git status --short --branch`、`git log -n 10 --oneline --decorate`，检查未提交改动、任务分支、`develop` 与远端指针。先保留已有工作，不清理或重置工作区。
2. 对照验收要求检查代码、测试和提交内容；将每项标为已完成、未完成或尚未验证。计划、聊天总结和子代理自述只是线索，不能代替 Git 与运行结果。已合并的工作不要重新实现；若任务分支仍未完成，沿用该分支继续。
3. 复查上次实际执行的命令及退出状态；对剩余风险运行针对性测试和适用的增量门禁。旧的 PASS 只证明当时的版本，代码变化或需要重新宣称完成时取得新鲜输出。测试继续隔离 `HOME`、`STELLA_DATA_DIR` 和工作区数据。
4. 审查子代理或 Skill 因额度失败时，将该步骤记为 `SKIP`，不写成通过。若仍可调用，补做独立审查；否则自行逐项检查 diff、需求与失败路径，继续其他已授权工作，并在交付中说明独立审查的限制。不要反复重试同一个额度错误。
5. 最后核对工作区、提交、目标分支和 PASS/FAIL/SKIP；按既有授权完成本地 `develop` 合并。未获授权时仍不推送远端、不改 `main`。

跨模块或持续多轮的任务，在 `docs/plans/active/` 的进度记录中维护目标和验收项、基线/工作分支与最新提交、未提交文件、已验证的命令及结果、未完成的审查与下一条可执行步骤。每次完成一个阶段或准备长时间操作前更新记录，使下一会话能直接续做。任务结束后按计划工作流归档，避免把临时状态长期留在 active 目录。

## 统一命令

在仓库根目录执行，默认使用 `.venv/bin/python`。`make setup` 创建本地虚拟环境、安装 Python/桌面依赖与 Chromium；不会安装全局 Skill。

| 命令 | 用途 |
| --- | --- |
| `make setup` | 初始化本地依赖 |
| `make dev` | 启动桌面热重载开发服务；需要正确安装 Electron |
| `make check` | 按变更文件选取增量 Ruff、pytest、桌面构建/类型/浏览器及项目规则检查 |
| `make lint` | Python Ruff、桌面 ESLint 与 TypeScript |
| `make test` | 完整 Python 测试集 |
| `make test-integration` | 关键 Agent、简报、权限和交付集成测试 |
| `make test-e2e` | 隔离的 Playwright 桌面 UI 检查 |
| `make eval` | 离线确定性 Agent 场景及项目规则静态检查 |
| `make audit` | 完整自动化门禁及结构化审计草稿 |

`scripts/quality_check.py` 和 `scripts/run_isolated.py` 为测试进程设置临时 `HOME`、`STELLA_DATA_DIR`、配置、缓存和临时目录，并移除提供商凭证。不要把真实用户目录作为测试参数。`make audit` 的报告只填入自动化证据，人工审查列仍标为待审；明确要求 `Full Audit`/`全项目体检` 时才按 `software-audit` Skill 完成领域审查报告。

## CI 与审查

`.github/workflows/project-quality.yml` 在向 `develop`/`main` 发起 PR、推送 `develop` 时运行 `make check`、`make eval`；手动触发时还运行 `make audit` 并保留审计报告。CI 为增量门禁传入 PR/push 的基线提交。现有 Windows Bash 工作流继续单独运行。CI 和本地共享 Make 命令；本地小改动优先 `make check`，跨模块或高风险改动补跑完整门禁。全量 Ruff 的历史发现仍会使 `make lint` 和 `make audit` 失败，完整报告保留这一事实，日常增量门禁会检查新改动。

仓库目前没有启用的项目 Git hook 或提交模板；质量门禁由开发流程和 CI 执行。远程 `main`、`develop` 的 GitHub branch protection API 在本次检查中均返回 `Branch not protected`（HTTP 404）。建议以后由仓库管理员设置必需 CI、PR 审查、禁止直接推送及强推；此设置属于远程管理变更，本次未修改。

依赖安装、浏览器下载和真实模型评测需要外部资源。离线 Agent Evals 使用 Mock，不代表真实模型完成率或任意提示注入抵抗力。代码与结果不一致时先定位、补回归测试并重跑；交付时分别列出 PASS、FAIL、SKIP。

## Codex 与外部工具

Codex 的根规则由 `AGENTS.md` 显式引到 `.agents/AGENTS.md`，项目配置位于 `.codex/config.toml`；项目级 Skills 放在 `.agents/skills/`，清单见 [技能维护](skills.md)。`codex mcp list --json` 本次列出 `code-review`、`codex_app`、`computer-use`、`cua_repl`、`node_repl`。加上现有 GitHub CLI、浏览器和测试工具，当前任务没有需要新登录或凭证的 MCP/插件。首次在新 Codex 会话使用新 Skill 时，按 [开发行为检查表](../../evals/codex-development.md) 抽查实际发现和使用情况。
