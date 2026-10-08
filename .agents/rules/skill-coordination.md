# Skill 协作规则

每次任务先看用户目标、已有代码、改动风险和预期交付。先决定是否需要规划，再选择任务本身的工作步骤和确有用途的辅助 Skill；复杂 Bug 可以先规划，在执行阶段逐项调试与测试。用户点名的 Skill 应纳入流程；仅因关键词相似不调用。开始前检查 Git 状态并遵守 [Git](git.md)、[测试](testing.md)与[安全](security.md)规则。Skill 的通用建议不得覆盖用户授权和项目规则。

## 选择工作步骤

| 任务 | 步骤 | 进入条件 |
| --- | --- | --- |
| 简单修改或说明 | 省略规划，按下列任务步骤直接处理 → `verification-before-completion` | 范围清楚、影响局部，不需要跨模块决策；纯答疑只验证所引用的事实 |
| 复杂开发 | `writing-plans` → `executing-plans` | 涉及多个模块、迁移、依赖顺序或较长任务；计划记入 `docs/plans/active/`，完成后归档 |
| Bug 或异常 | `systematic-debugging` → 复现与根因 → `test-driven-development` → 修复 | 先定位；需要修改可观察行为时先写失败的回归测试 |
| 新功能或行为修改 | `test-driven-development` → 实现 | 先定义可观察行为，运行失败测试后再写实现 |
| 明确要求完整审计 | `software-audit` | 用户说 `Full Audit`、`全项目体检` 或明确点名该 Skill；只读审查并交付证据报告 |
| 创建项目 Skill | Codex 内建 `skill-creator` | 产物仅放 `.agents/skills/`，核对元数据、依赖和项目使用场景 |

复杂任务的计划包住对应的 Bug、功能或 UI 工作步骤，不替代用户已经给出的实施授权；不要为了再次确认计划而停下。简单任务也要完成适用的检查。恢复中断任务时先核对 Git、代码和测试，再从尚未完成的步骤继续，避免重复开发。

## 按需加入的辅助 Skill

| 任务条件 | 协作方式 |
| --- | --- |
| 新建或重做 UI | `frontend-design` 在实现前确定信息层级、交互和视觉方向；React 代码适用时参考 `vercel-react-best-practices`；实现后用 `webapp-testing` 验证真实交互。 |
| 用户要求审查 UI、可访问性或 UX，或重大 UI 改动需要复核 | 用 `web-design-guidelines` 审查界面，发现问题后回到实现和浏览器验证。 |
| 权限、凭证、外部调用、数据库写入等安全敏感差异，或用户直接要求审查变更风险 | 在有可审查 diff 后用 `differential-review` 找风险与缺失测试；发现行为缺陷时回到 `systematic-debugging` 和 `test-driven-development`。 |
| 重大功能、跨模块修改、用户直接要求代码审查或合并前需要独立判断 | 用 `requesting-code-review` 请求审查，处理重要发现并重跑受影响检查。小型文档和低风险修改可自行检查 diff。 |

辅助 Skill 可以串行复用同一份代码和证据，不要求每项任务机械运行全部 Skill。UI 评审不代替浏览器测试；安全评审不代替权限测试；代码审查不代替最终验证。设计稿请求若明确只要设计，不进入功能开发。

## 收尾与反馈

1. 按改动范围运行隔离测试，读取失败输出并修复。需要审查的改动在审查后处理发现；若修复改变行为，补失败再通过的测试。
2. 最后用 `verification-before-completion` 对照用户要求、diff 和新鲜命令输出，再提交或宣称完成。分别报告 PASS、FAIL、SKIP，不把 Mock Evals 当作真实模型结果。
3. 按既有授权执行本地 `develop` 合并；推送、发布或更新 `main` 遵守 [Git 规则](git.md)。

缺少或不兼容的 Skill 不阻断常规工作：使用同等的普通工程步骤并说明跳过原因。若两个 Skill 的步骤冲突，以用户目标、项目规则、实际代码和可验证结果为准；只保留适用于当前任务的步骤。不要重复要求已经获得的授权。
