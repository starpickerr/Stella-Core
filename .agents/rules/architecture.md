# 架构规则

- 开始跨模块改动前，从 [开发者架构导航](../../docs/architecture/overview.md) 找到真实入口、服务、存储与测试；文档冲突时以代码和可复现行为为准并修正文档。
- `application/` 聚合业务端口，`agent/*/service.py` 承载领域规则，`agent/tools/` 是 Agent 调用适配层，`app.py` 与 `desktop/` 是入口。不要在 UI、HTTP handler 和 Agent tool 中复制独立业务规则。
- 新写入路径检查校验、权限、事务边界、幂等键与失败恢复。跨事务、日程、简报和调度的修改要验证实际执行结果与展示一致。
- 只为真实调用方增加抽象；保持接口兼容，数据迁移须考虑旧数据与重复执行。
