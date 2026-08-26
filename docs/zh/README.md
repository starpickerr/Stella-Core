<p align="center"><img src= "https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="Stella" width="420" /></p>

<p align="center">
  <a href="https://github.com/starpickerr/Stella/releases/latest"><img src="https://img.shields.io/github/v/release/starpickerr/Stella?cacheSeconds=3600" alt="Latest release" /></a>
  <a href="https://github.com/starpickerr/Stella/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" /></a>
  <a href="https://github.com/starpickerr/Stella"><img src="https://img.shields.io/github/stars/starpickerr/Stella?style=flat-square&cacheSeconds=3600" alt="Stars" /></a>
</p>

<p align="center">
  [<a href="../../README.md">English</a>] | [中文] | [<a href="README-Hant.md">繁體中文</a>] | [<a href="../ja/README.md">日本語</a>]
</p>

**Stella** 是一个 AI 私人秘书。它能规划任务、操作电脑和外部服务、记住重要信息，并逐步积累你的个人知识库，在网页、桌面和各类即时通讯里替你处理日常事务。

项目基于可扩展的 Agent Harness：可接入主流大模型，7×24 运行在个人电脑或服务器上，并用工具、技能和消息通道继续扩展。

<p align="center">
  <a href="https://github.com/starpickerr/Stella">🐙 GitHub</a> &nbsp;·&nbsp;
  <a href="intro/index.mdx">📖 文档</a> &nbsp;·&nbsp;
  <a href="guide/quick-start.mdx">🚀 快速开始</a>
</p>

<br/>

## 🎬 演示

<p align="center">
  <video src="https://github.com/user-attachments/assets/a2d8fb12-f294-42d6-a569-c4a6ceedab1d" controls muted playsinline width="720">
    你的浏览器无法播放该视频。
    <a href="https://cowagent.ai/?lang=zh">前往官网观看演示 →</a>
  </video>
</p>

<br/>

## 🌟 核心能力

| 能力 | 说明 |
| :--- | :--- |
| [任务规划](https://docs.cowagent.ai/zh/intro/architecture) | 理解复杂任务并自主分解执行，循环调用工具直到完成目标 |
| [长期记忆](https://docs.cowagent.ai/zh/memory) | 三层记忆架构（上下文 → 天级 → 核心），梦境蒸馏自动整理，支持关键词与向量混合检索 |
| [知识库](https://docs.cowagent.ai/zh/knowledge) | 自动整理结构化知识为 Markdown Wiki，构建持续增长的知识图谱，可视化浏览 |
| [自主进化](https://docs.cowagent.ai/zh/memory/self-evolution) | 自动复盘对话，优化技能、处理未完成事项、沉淀记忆与知识，在使用中持续成长 |
| [技能](https://docs.cowagent.ai/zh/skills) | 从 [Skill Hub](https://skills.cowagent.ai/)、GitHub、ClawHub 等一键安装；也可通过对话创造自定义技能 |
| [工具](https://docs.cowagent.ai/zh/tools) | 内置文件读写、终端、浏览器、定时任务、记忆检索、联网搜索等 10+ 工具，支持 MCP 协议 |
| [通道](https://docs.cowagent.ai/zh/channels) | 一个 Agent 同时接入 Web、微信、飞书、钉钉、企微、QQ、公众号、Telegram、Slack 等多个渠道 |
| 多模态 | 文本、图片、语音、文件全消息类型支持，覆盖识别、生成、收发 |
| [模型](https://docs.cowagent.ai/zh/models) | DeepSeek、Claude、Gemini、GPT、GLM、Qwen、Kimi、MiniMax、Doubao 等主流厂商，配置一行切换 |
| [部署](https://docs.cowagent.ai/zh/guide/quick-start) | 一键脚本安装，Web 控制台统一管理；本地、Docker、服务器多种部署方式 |

<br/>

## 🏗️ 架构总览

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/architecture/zh/architecture.jpg" alt="Stella Architecture" width="750"/>

Stella 是一个完整的 **Agent Harness**：消息从各类**通道**进入，**Agent Core** 结合记忆、知识库与可用工具/技能进行任务规划与决策，调用**模型**生成结果，再回传至原通道。各模块解耦清晰，按需扩展。

详见 [项目架构](https://docs.cowagent.ai/zh/intro/architecture)。

<br/>

## 🚀 快速开始

克隆本仓库，安装依赖后启动 Stella：

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
pip install -r requirements.txt
pip install -e .
stella start
```

**Docker：**

```bash
docker compose -f docker/docker-compose.yml up -d
```

启动成功后访问 `http://localhost:9899` 进入 **Web 控制台**，即可对话、配置模型、接入通道和安装技能。

> 服务器部署且需要公网访问控制台时，请在 `config.json` 中将 `web_host` 设为 `0.0.0.0`（同时强烈建议设置 `web_password` 启用鉴权），然后访问 `http://<server-ip>:9899`，并确保防火墙/安全组放行 `9899` 端口。

> 📖 仓库内指南：[快速开始](guide/quick-start.mdx) · [源码安装](guide/manual-install.mdx) · [升级](guide/upgrade.mdx)

安装后可使用 `stella` CLI 管理服务：

```bash
stella start | stop | restart        # 服务管理
stella status | logs                  # 状态和日志
stella update                         # 拉取最新代码并重启
stella skill install <名称>           # 安装技能
stella install-browser                # 安装浏览器工具
```

<br/>

## 🤖 模型支持

Stella 支持国内外主流厂商的大语言模型。**文本对话、图像理解、图像生成、语音识别/合成、向量** 等能力均可独立配置厂商。

| 厂商 | 代表模型 | 文本 | 图像理解 | 图像生成 | 语音识别 | 语音合成 | 向量 |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](https://docs.cowagent.ai/zh/models/deepseek) | deepseek-v4-flash / pro | ✅ | | | | | |
| [Claude](https://docs.cowagent.ai/zh/models/claude) | claude-opus-5 / sonnet-5 | ✅ | ✅ | | | | |
| [OpenAI](https://docs.cowagent.ai/zh/models/openai) | gpt-5.6 系列 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](https://docs.cowagent.ai/zh/models/gemini) | gemini-3.7-flash | ✅ | ✅ | ✅ | | | |
| [MiniMax](https://docs.cowagent.ai/zh/models/minimax) | MiniMax-M3 | ✅ | ✅ | ✅ | | ✅ | |
| [智谱 GLM](https://docs.cowagent.ai/zh/models/glm) | glm-5.3、glm-5v-turbo | ✅ | ✅ | | ✅ | | ✅ |
| [通义千问](https://docs.cowagent.ai/zh/models/qwen) | qwen3.8-max | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](https://docs.cowagent.ai/zh/models/kimi) | kimi-k3 | ✅ | ✅ | | | | |
| [豆包 Doubao](https://docs.cowagent.ai/zh/models/doubao) | doubao-seed-2.1 系列 | ✅ | ✅ | ✅ | | | ✅ |
| [百度ERNIE](https://docs.cowagent.ai/zh/models/qianfan) | ernie-5.1 | ✅ | ✅ | | | | |
| [小米 MiMo](https://docs.cowagent.ai/zh/models/mimo) | mimo-v2.5-pro / v2.5 | ✅ | ✅ | | | ✅ | |
| [LinkAI](https://docs.cowagent.ai/zh/models/linkai) | 一个 Key 接入 100+ 模型 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [自定义](https://docs.cowagent.ai/zh/models/custom) | 本地模型 / 三方代理 | ✅ | | | | | |

> 推荐通过 Web 控制台在线配置，无需手动编辑文件。手动配置请参考各厂商文档，详见 [模型概览](https://docs.cowagent.ai/zh/models)。

<br/>

## 💬 通道接入

一个 Agent 实例可同时接入多个渠道，启动时通过 `channel_type` 切换或并行运行。

| 通道 | 文本 | 图片 | 文件 | 语音 | 群聊 |
| --- | :-: | :-: | :-: | :-: | :-: |
| [Web 控制台](https://docs.cowagent.ai/zh/channels/web)（默认） | ✅ | ✅ | ✅ | ✅ | |
| [微信](https://docs.cowagent.ai/zh/channels/weixin) | ✅ | ✅ | ✅ | ✅ | |
| [飞书](https://docs.cowagent.ai/zh/channels/feishu) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [钉钉](https://docs.cowagent.ai/zh/channels/dingtalk) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [企微智能机器人](https://docs.cowagent.ai/zh/channels/wecom-bot) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](https://docs.cowagent.ai/zh/channels/qq) | ✅ | ✅ | ✅ | | ✅ |
| [企业微信应用](https://docs.cowagent.ai/zh/channels/wecom) | ✅ | ✅ | ✅ | ✅ | |
| [微信客服](https://docs.cowagent.ai/zh/channels/wechat-kf) | ✅ | ✅ | ✅ | ✅ | |
| [微信公众号](https://docs.cowagent.ai/zh/channels/wechatmp) | ✅ | ✅ | | ✅ | |
| [Telegram](https://docs.cowagent.ai/zh/channels/telegram) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](https://docs.cowagent.ai/zh/channels/slack) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](https://docs.cowagent.ai/zh/channels/discord) | ✅ | ✅ | ✅ | | ✅ |

> 飞书、企微智能机器人支持在 Web 控制台内**扫码一键接入**，无需公网 IP。详见 [通道概览](https://docs.cowagent.ai/zh/channels)。

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-chat.png" alt="Stella Web 控制台" width="800"/>

*Web 控制台是默认通道，也是统一的 Agent 配置和管理入口*

<br/>

## 🧠 记忆与知识库

**长期记忆**采用三层架构：对话上下文（短期）→ 天级记忆（中期）→ MEMORY.md（长期）。每日自动执行**梦境蒸馏（Deep Dream）**，将分散记忆整合为精炼的长期记忆并生成叙事日记。详见 [长期记忆](https://docs.cowagent.ai/zh/memory) · [梦境蒸馏](https://docs.cowagent.ai/zh/memory/deep-dream)。

**个人知识库** 与按时间记录的记忆不同，以**主题为维度**组织结构化知识。Agent 在对话中自动整理有价值信息，维护交叉引用与索引，Web 控制台可可视化浏览知识图谱。详见 [个人知识库](https://docs.cowagent.ai/zh/knowledge)。

<table>
  <tr>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-memory.png" alt="长期记忆" />
      <p align="center"><em>长期记忆 · 三层记忆 + 梦境蒸馏</em></p>
    </td>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/zh/web-console-knowledge.png" alt="个人知识库" />
      <p align="center"><em>个人知识库 · 自动整理的 Markdown Wiki</em></p>
    </td>
  </tr>
</table>

<br/>


## 🔧 工具与技能

**工具（Tools）** 是 Agent 操作系统资源的原子能力，**技能（Skills）** 是基于说明文件的高级工作流，可组合多个工具完成复杂任务。

### 工具系统

**内置工具** 涵盖文件读写（`read` / `write` / `edit` / `ls`）、终端（`bash`）、文件发送（`send`）、记忆检索（`memory`）、环境变量（`env_config`）、网页获取（`web_fetch`）、定时任务（`scheduler`）、联网搜索（`web_search`）、图像识别（`vision`）、浏览器自动化（`browser`）等常用能力。

**MCP 协议** 通过 [Model Context Protocol](https://modelcontextprotocol.io) 接入开放生态中的各种 MCP 服务，配置一次 `mcp.json` 即用即得，支持 stdio / SSE 协议、热更新、零代码接入。

详见 [工具概览](https://docs.cowagent.ai/zh/tools) · [MCP 集成](https://docs.cowagent.ai/zh/tools/mcp)。

### 技能系统

- **[Skill Hub](https://skills.cowagent.ai/)** — 开源的技能广场，浏览、搜索、一键安装
- **GitHub / ClawHub / URL 等** — 任意来源一键安装
- **对话创造** — 通过 `skill-creator` 用对话快速生成自定义技能，可将工作流程或第三方接口直接固化为技能

```bash
/skill list                   # 查看当前技能
/skill search <关键词>         # 在技能广场搜索
/skill install <名称>          # 一键安装
```

详见 [技能概览](https://docs.cowagent.ai/zh/skills) · [创建技能](https://docs.cowagent.ai/zh/skills/create)。

<br/>

## 🏷 更新日志

> **2026.08.20：** [v2.1.7](https://github.com/starpickerr/Stella/releases/tag/2.1.7) — 多工作空间与会话隔离、会话级权限模式、任务通知、桌面端优化、新模型接入

> **2026.08.12：** [v2.1.6](https://github.com/starpickerr/Stella/releases/tag/2.1.6) — 子 Agent 并行任务分配、推理强度配置、记忆向量库可插拔、体验和安全优化

> **2026.07.29：** [v2.1.5](https://github.com/starpickerr/Stella/releases/tag/2.1.5) — 工作空间与文件预览、基础工具优化（文件搜索、写入校验、命令后台运行）、上下文压缩（`/compact`）、提示词一键优化、安全加固

> **2026.07.20：** [v2.1.4](https://github.com/starpickerr/Stella/releases/tag/2.1.4) — 桌面客户端体验优化、MCP 支持 OAuth 授权、飞书通道能力增强、定时任务优化与数据备份、新模型接入

> **2026.07.08：** [v2.1.3](https://github.com/starpickerr/Stella/releases/tag/2.1.3) — [桌面客户端](https://cowagent.ai/zh/download/)正式发布（macOS / Windows）、知识库文档管理增强、MCP 工具智能检索、繁体中文支持、新模型接入

> **2026.06.18：** [v2.1.2](https://github.com/starpickerr/Stella/releases/tag/2.1.2) — Web 控制台升级（定时任务管理、知识库分类、多模型自定义厂商）、自主进化优化、新模型接入（kimi-k2.7-code、glm-5.2）、安全加固和体验优化

> **2026.06.09：** [v2.1.1](https://github.com/starpickerr/Stella/releases/tag/2.1.1) — 自进化能力、Web 控制台升级（消息管理、多会话并行）、新模型接入（MiniMax-M3、qwen3.7-plus）、Python 3.13 支持

> **2026.06.01：** [v2.1.0](https://github.com/starpickerr/Stella/releases/tag/2.1.0) — 国际化支持、新增通道（Telegram、Discord、Slack、微信客服）、命令行交互升级、一键安装脚本优化、MCP Streamable HTTP 支持、新模型接入（claude-opus-4-8、MiMo）

完整更新历史：[Release Notes](https://docs.cowagent.ai/zh/releases)

<br/>

## 🛠️ 开发

开发说明见 [CONTRIBUTING.md](/CONTRIBUTING.md)。本项目远程仓库为：

```bash
git remote set-url origin https://github.com/starpickerr/Stella.git
```

## ⚠️ 声明

1. 本项目遵循 [MIT 开源协议](/LICENSE)。使用时请遵守所在地法律法规，因使用本项目所产生的一切后果由使用者自行承担。
2. **成本与安全：** Agent 模式 Token 消耗显著高于普通对话。Stella 可以访问本地操作系统，请只在可信环境中部署。

## 📌 来源

Stella 是在 MIT 开源 Agent Harness 基础上改造的个人 AI 私人秘书项目。仓库地址：[github.com/starpickerr/Stella](https://github.com/starpickerr/Stella)。
