<p align="center"><img src= "../images/logo.jpg" alt="Stella" width="420" /></p>

<p align="center">
  <a href="https://github.com/starpickerr/Stella/releases/latest"><img src="https://img.shields.io/github/v/release/starpickerr/Stella?cacheSeconds=3600" alt="Latest release" /></a>
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" /></a>
  <a href="https://github.com/starpickerr/Stella"><img src="https://img.shields.io/github/stars/starpickerr/Stella?style=flat-square&cacheSeconds=3600" alt="Stars" /></a>
</p>

<p align="center">
  [<a href="../../README.md">English</a>] | [中文] | [<a href="README-Hant.md">繁體中文</a>] | [<a href="../ja/README.md">日本語</a>]
</p>

**Stella** 是一个 AI 私人秘书。它能规划任务、操作电脑和外部服务、记住重要信息，并逐步积累你的个人知识库，在桌面客户端和各类即时通讯里替你处理日常事务。

项目基于可扩展的 Agent Harness：可接入主流大模型，7×24 运行在个人电脑或服务器上，并用工具、技能和消息通道继续扩展。

<p align="center">
  <a href="https://github.com/starpickerr/Stella">🐙 GitHub</a> &nbsp;·&nbsp;
  <a href="intro/index.mdx">📖 文档</a> &nbsp;·&nbsp;
  <a href="guide/quick-start.mdx">🚀 快速开始</a>
</p>

<br/>

## 🌟 核心能力

| 能力 | 说明 |
| :--- | :--- |
| [任务规划](intro/architecture.mdx) | 理解复杂任务并自主分解执行，循环调用工具直到完成目标 |
| [长期记忆](memory/index.mdx) | 三层记忆架构（上下文 → 天级 → 核心），梦境蒸馏自动整理，支持关键词与向量混合检索 |
| [知识库](knowledge/index.mdx) | 自动整理结构化知识为 Markdown Wiki，构建持续增长的知识图谱，可视化浏览 |
| [自主进化](memory/self-evolution.mdx) | 自动复盘对话，优化技能、处理未完成事项、沉淀记忆与知识，在使用中持续成长 |
| [技能](skills/index.mdx) | 从 [skill广场](https://www.skill-marketplace.com/)、GitHub、ClawHub 等一键安装；也可通过对话创造自定义技能 |
| [工具](tools/index.mdx) | 内置文件读写、终端、浏览器、定时任务、记忆检索、联网搜索等 10+ 工具，支持 MCP 协议 |
| [通道](channels/index.mdx) | 一个 Agent 同时接入桌面客户端、微信、飞书、钉钉、企微、QQ、公众号、Telegram、Slack 等多个渠道 |
| 多模态 | 文本、图片、语音、文件全消息类型支持，覆盖识别、生成、收发 |
| [模型](models/index.mdx) | DeepSeek、Claude、Gemini、GPT、GLM、Qwen、Kimi、MiniMax、Doubao 等主流厂商，配置一行切换 |
| [部署](guide/quick-start.mdx) | Electron 桌面客户端与专用本地后端 |

<br/>

## 🏗️ 架构总览

Stella 是一个完整的 **Agent Harness**：消息从各类**通道**进入，**Agent Core** 结合记忆、知识库与可用工具/技能进行任务规划与决策，调用**模型**生成结果，再回传至原通道。各模块解耦清晰，按需扩展。

详见 [项目架构](intro/architecture.mdx)。

<br/>

## 🚀 快速开始

从 [GitHub Releases](https://github.com/starpickerr/Stella/releases/latest) 下载并打开 Electron 桌面客户端。开发者可从源码运行：

需要 Python 3.9+ 和 Node.js 22.13+。Windows 命令见[源码构建](guide/manual-install.mdx)。

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
cd desktop
npm run dev
```

`npm run dev` 每次都会构建当前界面并启动桌面专用后端。详见[快速开始](guide/quick-start.mdx)和[源码构建](guide/manual-install.mdx)。

<br/>

## 🤖 模型支持

Stella 支持国内外主流厂商的大语言模型。**文本对话、图像理解、图像生成、语音识别/合成、向量** 等能力均可独立配置厂商。

| 厂商 | 文本 | 图像理解 | 图像生成 | 语音识别 | 语音合成 | 向量 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](models/deepseek.mdx) | ✅ | | | | | |
| [Claude](models/claude.mdx) | ✅ | ✅ | | | | |
| [OpenAI](models/openai.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](models/gemini.mdx) | ✅ | ✅ | ✅ | | | |
| [MiniMax](models/minimax.mdx) | ✅ | ✅ | ✅ | | ✅ | |
| [智谱 GLM](models/glm.mdx) | ✅ | ✅ | | ✅ | | ✅ |
| [通义千问](models/qwen.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](models/kimi.mdx) | ✅ | ✅ | | | | |
| [豆包 Doubao](models/doubao.mdx) | ✅ | ✅ | ✅ | | | ✅ |
| [百度ERNIE](models/qianfan.mdx) | ✅ | ✅ | | | | |
| [小米 MiMo](models/mimo.mdx) | ✅ | ✅ | | | ✅ | |
| [LinkAI](models/linkai.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [自定义](models/custom.mdx) | ✅ | | | | | |

> 推荐通过 桌面客户端在线配置，无需手动编辑文件。手动配置请参考各厂商文档，详见 [模型概览](models/index.mdx)。

<br/>

## 💬 通道接入

一个 Agent 实例可同时接入多个渠道，启动时通过 `channel_type` 切换或并行运行。

| 通道 | 文本 | 图片 | 文件 | 语音 | 群聊 |
| --- | :-: | :-: | :-: | :-: | :-: |
| [桌面客户端](guide/desktop.mdx)（默认） | ✅ | ✅ | ✅ | ✅ | |
| [微信](channels/weixin.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [飞书](channels/feishu.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [钉钉](channels/dingtalk.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [企微智能机器人](channels/wecom-bot.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](channels/qq.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [企业微信应用](channels/wecom.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [微信客服](channels/wechat-kf.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [微信公众号](channels/wechatmp.mdx) | ✅ | ✅ | | ✅ | |
| [Telegram](channels/telegram.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](channels/slack.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](channels/discord.mdx) | ✅ | ✅ | ✅ | | ✅ |

> 飞书、企微智能机器人支持在桌面客户端内**扫码一键接入**，无需公网 IP。详见 [通道概览](channels/index.mdx)。

*桌面客户端是默认通道，也是统一的 Agent 配置和管理入口*

<br/>

## 🧠 记忆与知识库

**长期记忆**采用三层架构：对话上下文（短期）→ 天级记忆（中期）→ MEMORY.md（长期）。每日自动执行**梦境蒸馏（Deep Dream）**，将分散记忆整合为精炼的长期记忆并生成叙事日记。详见 [长期记忆](memory/index.mdx) · [梦境蒸馏](memory/deep-dream.mdx)。

**个人知识库** 与按时间记录的记忆不同，以**主题为维度**组织结构化知识。Agent 在对话中自动整理有价值信息，维护交叉引用与索引，桌面客户端可视化浏览知识图谱。详见 [个人知识库](knowledge/index.mdx)。

<br/>

## 🔧 工具与技能

**工具（Tools）** 是 Agent 操作系统资源的原子能力，**技能（Skills）** 是基于说明文件的高级工作流，可组合多个工具完成复杂任务。

### 工具系统

**内置工具** 涵盖文件读写（`read` / `write` / `edit` / `ls`）、终端（`bash`）、文件发送（`send`）、记忆检索（`memory`）、环境变量（`env_config`）、网页获取（`web_fetch`）、定时任务（`scheduler`）、联网搜索（`web_search`）、图像识别（`vision`）、浏览器自动化（`browser`）等常用能力。

**MCP 协议** 通过 [Model Context Protocol](https://modelcontextprotocol.io) 接入开放生态中的各种 MCP 服务，配置一次 `mcp.json` 即用即得，支持 stdio / SSE 协议、热更新、零代码接入。

详见 [工具概览](tools/index.mdx) · [MCP 集成](tools/mcp.mdx)。

### 技能系统

- **[skill广场](https://www.skill-marketplace.com/)** — 浏览、搜索、一键安装
- **GitHub / ClawHub / URL 等** — 任意来源一键安装
- **对话创造** — 通过 `skill-creator` 用对话快速生成自定义技能，可将工作流程或第三方接口直接固化为技能

```bash
/skill list                   # 查看当前技能
/skill search <关键词>         # 在 skill广场搜索
/skill install <名称>          # 一键安装
```

详见 [技能概览](skills/index.mdx) · [创建技能](skills/create.mdx)。

<br/>

## 🏷 更新日志

> **2026.09.07：** [v0.0.1](https://github.com/starpickerr/Stella/releases/tag/v0.0.1) — Stella 首个测试版。桌面端发现新版本后提示并打开 GitHub Release 手动下载（macOS 只提供 `.dmg`）。产品版本号以仓库根目录 `VERSION` 为准。

发版步骤见 [desktop/README.md](../../desktop/README.md)。完整说明：[Release Notes](releases/overview.mdx)

<br/>

## 🛠️ 开发

开发说明见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。

## ⚠️ 声明

1. 本项目遵循 [MIT 开源协议](../../LICENSE)。使用时请遵守所在地法律法规，因使用本项目所产生的一切后果由使用者自行承担。
2. **成本与安全：** Agent 模式 Token 消耗显著高于普通对话。Stella 可以访问本地操作系统，请只在可信环境中部署。

## 📌 来源

Stella 是在 MIT 开源 Agent Harness 基础上改造的个人 AI 私人秘书项目。仓库地址：[github.com/starpickerr/Stella](https://github.com/starpickerr/Stella)。
