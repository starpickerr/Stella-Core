# Stella 开发者架构导航

本文记录当前代码，产品使用方式见[使用指南](../guide.md)。目录名与入口均以仓库当前实现为准；未来设想不在此标为已实现。

```mermaid
flowchart LR
  Desktop[desktop Electron/React] --> Web[channel/desktop HTTP API]
  Channel[channel/*] --> Bridge[bridge/*]
  Web --> App[application.api Application]
  Bridge --> Agent[agent/protocol/agent_stream.py]
  Agent --> Tools[agent/tools/*]
  Tools --> App
  Scheduler[agent/scheduler/*] --> App
  App --> Domain[agent/{todos,calendar,briefing} services]
  App --> Bills[stella.bills plugin RPC]
  Domain --> Data[common.state_dir 管理的 SQLite]
  Agent --> Gate[agent/runtime + agent/permission]
```

| 关注点 | 当前实现 | 入口与测试 |
| --- | --- | --- |
| 桌面 | Electron 主进程管理 Python 后端，React 经 API 访问业务 | `desktop/src/main/`, `desktop/src/renderer/`, `tests/ui_smoke.py` |
| HTTP 与通道 | `app.py` 启动应用；`channel/desktop/desktop_channel.py` 暴露桌面 HTTP API，其他 `channel/` 处理外部与 Web 消息 | `app.py`, `channel/`, `tests/test_briefing_web.py` |
| Agent/Harness | `bridge/` 组装模型、工具与会话；执行循环在 `agent/protocol/agent_stream.py` | [运行机制](agent-runtime.md) |
| 共享业务边界 | `Application.port` 和 `Application.command` 将 Desktop、Agent 工具、自动化送入同一领域服务 | `application/api.py`, `tests/test_todos.py`, `tests/test_harness_runtime.py` |
| 领域服务 | `agent/briefing/` 来源/生成适配、`scheduler/`；简报存储与决策通过 `core/services/briefing_facade.py`，日程通过 `core/services/calendar_facade.py`，账单与事务通过 `core/services/bills_facade.py`、`todos_facade.py` 调用外仓插件，`agent/calendar/`、`agent/todos/` 只保留 Apple 与 scheduler 适配 | [业务模块](../modules/core-business.md) |
| 状态与权限 | `common/runtime_identity.py`、`common/state_dir.py` 分配身份与路径；运行时权限由 gateway 决定 | [数据与安全](security-and-storage.md) |
| 知识与长期记忆 | `stella.knowledge`、`stella.memory` 各自提供文档、索引、检索、整理和上下文贡献，入口经 `core/services/*_facade.py` 与 gateway 调用独立 worker。Core 仅保留 `agent/memory/conversation_store.py` 的会话存储，以及 `models/plugin_service.py` 的授权模型接口 | `tests/test_knowledge_plugin_boundary.py`；外仓 `Stella-Plugins/plugins/{knowledge,memory}` |

知识和记忆默认安装，可独立停用；不可用时不回退到 Core 业务实现。管理页面由插件声明贡献，React 宿主复用现有页面。知识沿用用户的 `knowledge/`，长期记忆首次迁入用户根目录的 `plugins/memory/`，旧 Markdown 保留且不再作为运行时写入目标。Core 会话数据库留在原路径，停用长期记忆不影响对话记录。迁移及安装测试使用隔离数据，已有安装包需重新构建才能包含这两个默认插件。

更详细的数据路径见 [数据流](data-flow.md)。修改跨模块写入时，先定位 `Application` 命令与对应领域服务，检查是否已有幂等与恢复机制。

## 邮箱与 eLearning MCP

邮箱与学校抓取分别由工作区 `MCP/email-mcp`、`MCP/fudan-elearning-mcp` 独立仓库发布本地 stdio Server。Core 的 `core/mcp/managed.py` 注册可信默认连接；设置、简报与 Agent 通过同一 `ToolManager.call_mcp_tool` 使用 MCP Runtime。管理工具不注入 Agent；公开工具保留来源、启停、权限及取消。旧插件不再安装或启动，原有账号、cookies、SQLite、游标及下载文件保持原路径格式，由 Server 接管。

迁移不抹除旧连接拒绝、插件授权撤销、后台用途或课程/文件夹范围。既有 scoped grants 由 Core 兼容检查，并通过 MCP 请求元数据向 Server 传递实际资源约束；该元数据不属于 Agent 可写工具参数。原生设置点击仅确认需要确认的操作，不能覆盖拒绝或为 Agent/后台调用确认。eLearning 下载仍需 Core 文件写权限，Server 限定配置根目录并保护本地文件。独立 eLearning 客户端用跨进程锁保护共享游标、审计和下载 manifest。

开发启动发现兄弟 MCP 仓库的环境；独立部署可安装 console script。桌面构建调用各仓库 `build_mcp.py`，将独立冻结 Server 产物放在 backend 同级目录；缺失环境会明确构建失败，不回退旧插件或把冻结 backend 当作 Python。测试：`tests/test_managed_mcp_domains.py`、`tests/test_mcp_bound_resources.py`。

## 数据服务

`core/data` 提供用户级通用来源、采集检查点、去重记录与可靠变更通知。邮箱提供者集中映射一次 MCP，简报通过通用 DataSource 或受信消费者读取，权限继续由现有 Security/MCP/Tool Runtime 决定。设置「数据管理」负责数据生命周期，安全中心「数据访问」负责访问策略。契约、事件语义与阶段范围见 [数据服务](data-service.md)。
