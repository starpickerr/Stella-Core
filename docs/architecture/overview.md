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
  App --> Domain[agent/{todos,calendar,bills,briefing} services]
  Domain --> Data[common.state_dir 管理的 SQLite]
  Agent --> Gate[agent/runtime + agent/permission]
```

| 关注点 | 当前实现 | 入口与测试 |
| --- | --- | --- |
| 桌面 | Electron 主进程管理 Python 后端，React 经 API 访问业务 | `desktop/src/main/`, `desktop/src/renderer/`, `tests/ui_smoke.py` |
| HTTP 与通道 | `app.py` 启动应用；`channel/desktop/desktop_channel.py` 暴露桌面 HTTP API，其他 `channel/` 处理外部与 Web 消息 | `app.py`, `channel/`, `tests/test_briefing_web.py` |
| Agent/Harness | `bridge/` 组装模型、工具与会话；执行循环在 `agent/protocol/agent_stream.py` | [运行机制](agent-runtime.md) |
| 共享业务边界 | `Application.port` 和 `Application.command` 将 Desktop、Agent 工具、自动化送入同一领域服务 | `application/api.py`, `tests/test_todos.py`, `tests/test_harness_runtime.py` |
| 领域服务 | `agent/todos/`, `calendar/`, `bills/`, `briefing/`, `scheduler/` | [业务模块](../modules/core-business.md) |
| 状态与权限 | `common/runtime_identity.py`、`common/state_dir.py` 分配身份与路径；运行时权限由 gateway 决定 | [数据与安全](security-and-storage.md) |

更详细的数据路径见 [数据流](data-flow.md)。修改跨模块写入时，先定位 `Application` 命令与对应领域服务，检查是否已有幂等与恢复机制。
