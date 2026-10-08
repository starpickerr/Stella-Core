# 项目级 Skill 清单与维护

Skill 仅存于 `.agents/skills/`。任务中的选择与配合见 [Skill 协作规则](../../.agents/rules/skill-coordination.md)。上游仓库、固定 commit、原始 `SKILL.md` SHA-256 与本地适配记录在 [`sources.json`](../../.agents/skills/sources.json)。项目原有 Skill 不被覆盖。`scripts/check_dev_policy.py` 检查每个 Skill 的前置元数据、目录名称与清单一致性。

| 来源 | 已安装/保留 | 许可证与说明 |
| --- | --- | --- |
| obra/superpowers | `systematic-debugging`, `verification-before-completion`, `test-driven-development`, `requesting-code-review`, `writing-plans`, `executing-plans` | MIT；后两项本轮增加，其余保留项目已有版本；`executing-plans` 补入运行所需的三个上游 workspace 脚本并改为本目录调用 |
| anthropics/skills | `webapp-testing`, `frontend-design` | 各 Skill Apache-2.0；前者保留，后者本轮增加 |
| vercel-labs/agent-skills | `web-design-guidelines`, `vercel-react-best-practices` | 仓库 README 标为 MIT；前者把不可用的 `WebFetch` 引用改为当前浏览工具，后者只用于适用的 React 代码 |
| trailofbits/skills | `differential-review` | CC-BY-SA-4.0；附带方法文档，插件子代理为可选项 |
| Stella | `software-audit` | 项目已有的只读完整审计流程 |

没有复制 Anthropic 的 `skill-creator`：上游流程依赖 Claude CLI，且当前 Codex 已有同名内建 Skill。创建 Stella 项目 Skill 时使用 Codex 内建 `skill-creator`，产物仍只放 `.agents/skills/`；不要在项目中维护冲突副本。

上游 Skill 内的脚本、代理模板或网络链接不会自动执行。使用前按需阅读入口与相关资源；需浏览的最新外部指南使用可用浏览工具获取。仅为当前任务选择必要 Skill，不把其通用建议凌驾于 Stella 的数据隔离和分支规则。更新 Skill 时先核对上游路径、许可证、依赖与差异，再更新固定 commit、hash 和本地适配说明。

本次静态检查证明目录和元数据可被项目规则识别；新会话中的 Codex 实际发现与调用需要按 [`evals/codex-development.md`](../../evals/codex-development.md) 抽查，不能由静态检查代替。
