# Stella 产品 Agent 评测

`evals/` 只评测 Stella 产品 Agent。它不评测 Codex、Cursor 或其他开发 Agent。开发 Agent 的行为检查在 [`.agents/workflows/development-evaluation.md`](../.agents/workflows/development-evaluation.md)，静态规则检查是 `scripts/check_dev_policy.py`。

`make eval` 只运行 `evals/run.py`：按 `datasets/agent_cases.json` 中的情景逐项执行真实服务/工具测试，用测试退出码评分，并在 `evals/reports/latest.json` 保存每项证据。每项使用独立临时用户目录和数据库，不连接提供商。覆盖工具选择、参数、多步骤、权限、幂等、失败恢复与执行回执。它是确定性 Mock/脚本模型评测，不能冒充真实模型完成率或抵抗任意提示注入的证明。外部模型评测按需另建预算与凭证方案，不由本命令自动调用。
