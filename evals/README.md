# Agent 与 Codex 开发行为评测

`make eval` 运行 `evals/run.py`：按 `datasets/agent_cases.json` 中的情景逐项执行真实服务/工具测试，用测试退出码评分，并在 `evals/reports/latest.json` 保存每项证据。每项使用独立临时用户目录和数据库，不连接提供商。覆盖工具选择、参数、多步骤、权限、幂等、失败恢复与执行回执。它是**确定性 Mock/脚本模型评测**，不能冒充真实模型完成率或抵抗任意提示注入的证明。

Codex 行为评测见 [开发行为检查表](codex-development.md)。静态检查由 `scripts/check_dev_policy.py` 执行，真实 Codex 会话的遵规表现需在隔离副本中人工或专门受控运行确认。外部模型评测按需另建预算与凭证方案，不由本命令自动调用。
