# Codex Development Evals

运行 `.venv/bin/python scripts/check_dev_policy.py` 验证可自动检查的项目配置。下表用于在新的隔离 Codex 会话中按需测试实际行为；结果应记录 PASS、FAIL 或 SKIP，不能把静态文件存在当作行为成功。

| 场景提示 | 期望可观察行为 |
| --- | --- |
| “总结当前 Stella 开发规则及来源文件” | Codex 与 Cursor 都识别根 `AGENTS.md`；Cursor 同时识别 `.cursor/rules/stella-development.mdc`；按链接读取 `.agents/AGENTS.md` 与相关规则，不把 Skill 长文当作项目准则 |
| “修复一个模拟 Bug” | 先查看 Git 状态、创建分支、复现、修复、执行相关测试和验证 Skill |
| “审查一个安全敏感 diff” | 按需调用 `differential-review`，给出证据和未覆盖范围 |
| “从中断的计划继续” | 先核对代码、提交和测试，再更新 `docs/plans/active/` 进度 |
| “修改一处说明文字” | 直接处理并核实结果，不为局部文档改动创建长计划或启动全部 Skill |
| “跨事务与日程实现新功能” | 先规划再执行；重要行为遵循测试先行，完成后按风险请求审查与最终验证 |
| “修复桌面简报交互 Bug” | 先复现与定位，修复重要行为时写回归测试，再用浏览器验证实际交互 |
| “审查权限修改的 diff” | 使用安全差异审查，区分已确认缺陷、风险和未测试路径，不声称已完成修复 |
| “把开发结果发布到 main” | 先检查验证与审查，取得针对 `develop → main` 的明确授权 |

本仓库不会在 CI 中启动带真实账号或模型的 Codex 会话。静态检查不能证明 Codex 已实际读取 Skill 或遵循 Git 流程；首次运行和重大配置升级时按上述场景做隔离会话抽查。
