<p align="center"><img src="../images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](../../README.md) · [中文](README.md) · [繁體中文](README-Hant.md) · [日本語](../ja/README.md)

Stella 是桌面 AI 私人助理，集成对话、事务、日程、账单和简报。Electron 客户端与专用 Python 后端在本机运行。

本项目基于 zhayujie 及贡献者开发的 [CowAgent](https://github.com/zhayujie/CowAgent)（原 `chatgpt-on-wechat`）独立开发，复用上游的 Agent、模型、工具、技能、记忆和消息通道基础。Stella 在此基础上增加桌面工作流，以及事务、日程、账单、简报和安全管理等共享业务服务。来源与版权见[第三方声明](../../THIRD_PARTY_NOTICES.md)及 [MIT 许可证](../../LICENSE)。

## 主要功能

- 配置模型厂商和自定义厂商，为支持的能力分别选择模型。
- 管理事务、日程、账单，以及从邮箱和 eLearning 收集的信息。
- 按用户设置的时间运行自动化，查看执行记录，并通过已配置通道投递结果。
- 管理工具、技能、MCP、记忆、知识库和外部消息连接。
- 在安全中心管理全局、项目和会话权限。

## 开始使用

可用安装包见 [GitHub Releases](https://github.com/starpickerr/Stella/releases)。从最新源码运行需要 **Python 3.10+** 和 **Node.js 22.13+**；macOS 还需要 Xcode 命令行工具（`xcode-select --install`）。

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows 命令、浏览器准备、首次配置及本地数据说明见[使用指南](guide.md)。界面热更新使用 `npm --prefix desktop run dev:hot`。

## 文档与开发

- [使用指南](guide.md)：安装、配置与日常使用。
- [文档索引](../README.md)：当前架构、业务模块和安全边界。
- [桌面开发](../../desktop/README.md)：构建和打包。
- [贡献指南](../../CONTRIBUTING.md)：开发环境与检查；从 `develop` 开始修改，`main` 用于发布。
- [问题反馈](https://github.com/starpickerr/Stella/issues)：提交问题前，请从日志中删除凭据和个人信息。

模型调用可能产生厂商费用。工具可以访问本地文件和外部服务，请先配置权限。本地数据可能包含凭据和个人信息，不要提交到公开仓库。
