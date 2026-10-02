# 桌面本地 HTTP 适配器

此目录保留 Electron 客户端使用的 Python 本地 API、聊天 SSE、上传和健康检查。
浏览器页面与静态资源已经退役。桌面客户端负责启动后端、选择本地端口和展示界面；参见 [desktop/README.md](../../desktop/README.md)。

后端只在 Electron 启动时运行，绑定 `127.0.0.1`，业务 API 使用 Electron 主进程持有的临时令牌。`channel_type=web` 仅作为已有会话和定时任务的数据标识保留，不再提供 Web 客户端。
