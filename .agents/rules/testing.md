# 测试与验证规则

1. 映射改动文件到受影响模块与测试。默认运行 `.venv/bin/python scripts/quality_check.py incremental`；`--files` 可指定范围。
2. 重要 Bug 和业务逻辑增加失败再通过的针对性测试。权限、数据库、并发、迁移和 Agent 工具同时覆盖拒绝/失败及恢复。UI 在类型检查之外运行 Playwright 关键交互。
3. 门禁使用隔离的 `HOME`、`STELLA_DATA_DIR`、缓存和临时目录；手工测试也须使用隔离数据。不得连接真实账号或外部服务。
4. 失败时先定位原因、修复并重跑受影响检查。不要删除失败测试、降低断言或将未运行项写成 PASS。
5. 范围或风险需要时运行 `.venv/bin/python scripts/quality_check.py full`。完整审计按 `software-audit` Skill 人工补全证据与限制，不能把自动模板当作完成报告。
