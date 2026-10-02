# 桌面本地 HTTP 适配器

此目录保留 Electron 客户端使用的 Python 本地 API、聊天 SSE、上传和健康检查。
浏览器页面与静态资源已经退役。桌面客户端负责启动后端、选择本地端口和展示界面；参见 [desktop/README.md](../../desktop/README.md)。

`WebChannel` 和 `channel_type=web` 仍用于现有聊天会话与渠道兼容，后续协议迁移再统一更名。
