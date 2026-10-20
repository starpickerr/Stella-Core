<p align="center"><img src="../images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](../../README.md) · [中文](README.md) · [繁體中文](README-Hant.md) · [日本語](../ja/README.md)

**Stella 是一款桌面端私人 AI 助理**，以智能对话为核心，将事务、日程、账单、智能简报和自动化任务集中在一个工作空间中。

## 主要功能

### 对话

通过自然语言与 AI 交互，支持问题解答、内容创作、信息检索和复杂任务执行，并提供项目与会话管理。

### 应用

| 模块 | 功能说明 |
| ---- | -------- |
| **事务** | 管理个人事务及多级子事务，设置截止时间、优先级和提醒，跟踪进展，支持与 Apple 提醒事项同步。 |
| **日程** | 管理日程与时间安排，提供日历视图、分类和提醒，支持与 Apple 日历同步。 |
| **简报** | 汇总邮箱、eLearning、日程和事务信息，提取重要事项、待办任务及临近截止时间，生成个性化智能简报。 |
| **账单** | 记录收入与支出，支持账单分类、查询和统计分析。 |
| **定时** | 管理自动化任务，按指定时间执行，查看执行记录，并通过已配置的消息通道推送结果。 |

### 信息

| 模块 | 功能说明 |
| ---- | -------- |
| **记忆** | 管理 AI 长期记忆，保存用户偏好和重要上下文，支持个性化交互。 |
| **知识** | 管理个人知识库，支持知识存储、检索和引用，为 AI 提供知识来源。 |

### 通道

连接和管理微信、飞书、Telegram 等外部消息平台，支持跨平台交互与消息通知。

### 系统

| 模块 | 功能说明 |
| ---- | -------- |
| **能力** | 查看和管理 AI 工具、Skills 等扩展能力，增强信息获取与任务执行能力。 |
| **安全** | 管理全局、项目、会话及后台任务权限，控制工具调用和敏感操作，查看安全活动。 |
| **设置** | 配置 AI 模型厂商、自定义模型、模型能力分配、Apple 集成、简报及其他应用设置。 |
| **日志** | 查看运行日志、错误信息和执行记录，辅助故障排查与运行状态分析。 |

## 开始使用

### 下载安装包

可用安装包见 [GitHub Releases](https://github.com/starpickerr/Stella/releases)。安装、首次配置及日常使用见[使用指南](guide.md)。

### 从源码运行

环境要求：

- **Python 3.10+**
- **Node.js 22.13+**
- **macOS**：还需安装 Xcode 命令行工具，执行 `xcode-select --install`。

以下命令适用于 macOS；Windows 命令见[使用指南](guide.md)。

本地开发统一使用 Conda 的 `Stella` 环境（Python 3.12）；已有环境时跳过创建命令。

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
conda create -n Stella python=3.12
conda activate Stella
python -m pip install --upgrade pip setuptools
python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

开发时启用界面热更新：

```bash
npm --prefix desktop run dev:hot
```

浏览器准备和本地数据说明见[使用指南](guide.md)。

模型调用可能产生厂商费用。工具可以访问本地文件和外部服务，使用前请先配置权限。

## 文档与开发

- [使用指南](guide.md)：安装、配置与日常使用。
- [文档索引](../README.md)：架构、业务模块与安全边界。
- [桌面开发](../../desktop/README.md)：构建和打包。
- [贡献指南](../../CONTRIBUTING.md)：开发环境与检查要求；开发以 `develop` 为基线，`main` 用于发布。
- [问题反馈](https://github.com/starpickerr/Stella/issues)：提交问题前，请从日志中删除凭据和个人信息。

## 项目来源与许可

Stella 基于 zhayujie 及贡献者开发的 [CowAgent](https://github.com/zhayujie/CowAgent)（原 `chatgpt-on-wechat`）独立开发，复用上游的 Agent、模型、工具、技能、记忆和消息通道基础，并增加桌面工作流，以及事务、日程、账单、简报和安全管理等共享业务服务。

来源与版权说明见[第三方声明](../../THIRD_PARTY_NOTICES.md)，许可条款见 [MIT 许可证](../../LICENSE)。

## 作者的话

这是我第一次独立完成的开源项目，感谢 Codex 和 Cursor 在开发过程中提供的帮助。项目仍有需要完善的地方，欢迎通过[问题反馈](https://github.com/starpickerr/Stella/issues)提交建议和缺陷报告。
