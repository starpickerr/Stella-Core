# 开发与验证工作流

## 开始与恢复

1. 在仓库根目录检查 `git status --short --branch`、近期提交和相关代码。保留所有未提交内容。
2. 从当前 `develop` 建专用分支；复杂任务在 `docs/plans/active/` 写目标、验收、决策、已完成工作和下一步。恢复时以代码和测试核实计划条目。
3. 按 [架构导航](../architecture/overview.md) 找服务入口、数据路径与对应测试；按需读取 `.agents/rules/`。
4. 功能与测试在分支提交。用户已经授权完成功能后合并本地 `develop`；发布到 `main` 或推送远程需要另行明确授权。

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
