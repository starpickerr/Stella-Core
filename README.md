<p align="center"><img src="docs/images/logo.jpg" alt="Stella" width="420" /></p>

<p align="center">
  <a href="https://github.com/starpickerr/Stella/releases/latest"><img src="https://img.shields.io/github/v/release/starpickerr/Stella?cacheSeconds=3600" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://github.com/starpickerr/Stella"><img src="https://img.shields.io/github/stars/starpickerr/Stella?style=flat-square&cacheSeconds=3600" alt="Stars"></a>
</p>

<p align="center">
  [English] | [<a href="docs/zh/README.md">中文</a>] | [<a href="docs/zh/README-Hant.md">繁體中文</a>] | [<a href="docs/ja/README.md">日本語</a>]
</p>

**Stella** is a personal AI secretary. It plans tasks, uses your computer and external services, remembers what matters, and grows a private knowledge base — so it can handle everyday work on your behalf through the desktop client and messaging apps.

The codebase is an Agent Harness: plug in any major LLM, run it through the Electron desktop client, and extend it with tools, skills, and channels.

<p align="center">
  <a href="https://github.com/starpickerr/Stella">🐙 GitHub</a> &nbsp;·&nbsp;
  <a href="docs/intro/index.mdx">📖 Docs</a> &nbsp;·&nbsp;
  <a href="docs/guide/quick-start.mdx">🚀 Quick Start</a>
</p>

<br/>

## 🌟 Highlights

| Capability | Description |
| :--- | :--- |
| [Planning](docs/intro/architecture.mdx) | Decomposes complex tasks and executes them step by step, looping over tools until the goal is reached |
| [Memory](docs/memory/index.mdx) | Three-tier architecture (context → daily → core), automatic Deep Dream distillation, hybrid keyword + vector retrieval |
| [Knowledge](docs/knowledge/index.mdx) | Auto-curates structured knowledge into a Markdown wiki, builds an evolving knowledge graph with visual browsing |
| [Evolution](docs/memory/self-evolution.mdx) | Self-Evolution reviews conversations automatically to improve skills, follow up on unfinished tasks, and consolidate memory and knowledge, growing through everyday use |
| [Skills](docs/skills/index.mdx) | One-click install from [skill广场](https://www.skill-marketplace.com/), GitHub, ClawHub; or create custom skills via natural-language conversation |
| [Tools](docs/tools/index.mdx) | Built-in file I/O, terminal, browser, scheduler, memory retrieval, web search, and 10+ more tools — with native MCP integration |
| [Channels](docs/channels/index.mdx) | Integrates with the desktop client, WeChat, Feishu, DingTalk, WeCom, QQ, Official Accounts, Telegram, and Slack |
| Multimodal | First-class support for text, images, voice, and files — recognition, generation, and delivery |
| [Models](docs/models/index.mdx) | Claude, GPT, Gemini, DeepSeek, Qwen, GLM, Kimi, MiniMax, Doubao, and more — swap providers from the desktop client with one click |
| [Deploy](docs/guide/quick-start.mdx) | Electron desktop client with a private local backend |

<br/>

## 🏗️ Architecture

Stella is a complete **Agent Harness**: messages flow in through **Channels**; the **Agent Core** plans and reasons over memory, knowledge, and the available tools and skills; **Models** generate the response, which is sent back through the originating channel. Every layer is decoupled and independently extensible.

Read more in [Architecture](docs/intro/architecture.mdx).

<br/>

## 🚀 Quick Start

Download the desktop app from [Releases](https://github.com/starpickerr/Stella/releases/latest), or run the current source locally:

Requires Python 3.9+ and Node.js 22.13+. Windows commands are in [Build from Source](docs/guide/manual-install.mdx).

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
cd desktop
npm run dev
```

`npm run dev` builds the current Electron UI and starts its private Python backend. To work with hot UI reload, use `npm run dev:hot`.

> 📖 See [Desktop development](desktop/README.md) for packaging instructions.

<br/>

## 🤖 Models

Stella supports all mainstream LLM providers. **Chat, vision, image generation, ASR/TTS, and embeddings** can each be routed to a different vendor. Providers are configured in the desktop client.

| Provider | Chat | Vision | Image Gen | ASR | TTS | Embedding |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](docs/models/deepseek.mdx) | ✅ | | | | | |
| [Claude](docs/models/claude.mdx) | ✅ | ✅ | | | | |
| [OpenAI](docs/models/openai.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](docs/models/gemini.mdx) | ✅ | ✅ | ✅ | | | |
| [MiniMax](docs/models/minimax.mdx) | ✅ | ✅ | ✅ | | ✅ | |
| [GLM](docs/models/glm.mdx) | ✅ | ✅ | | ✅ | | ✅ |
| [Qwen](docs/models/qwen.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](docs/models/kimi.mdx) | ✅ | ✅ | | | | |
| [Doubao](docs/models/doubao.mdx) | ✅ | ✅ | ✅ | | | ✅ |
| [ERNIE](docs/models/qianfan.mdx) | ✅ | ✅ | | | | |
| [MiMo](docs/models/mimo.mdx) | ✅ | ✅ | | | ✅ | |
| [LinkAI](docs/models/linkai.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Custom](docs/models/custom.mdx) | ✅ | | | | | |

> For details on each provider, see the [Models overview](docs/models/index.mdx).

<br/>

## 💬 Channels

A single Agent instance can serve multiple channels in parallel. Channels can be connected from the desktop client.

| Channel | Text | Image | File | Voice | Group |
| --- | :-: | :-: | :-: | :-: | :-: |
| [Desktop client](docs/guide/desktop.mdx) (default) | ✅ | ✅ | ✅ | ✅ | |
| [Telegram](docs/channels/telegram.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](docs/channels/slack.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](docs/channels/discord.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [WeChat](docs/channels/weixin.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [Feishu / Lark](docs/channels/feishu.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [DingTalk](docs/channels/dingtalk.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [WeCom Bot](docs/channels/wecom-bot.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](docs/channels/qq.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [WeCom App](docs/channels/wecom.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat Customer Service](docs/channels/wechat-kf.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat Official Account](docs/channels/wechatmp.mdx) | ✅ | ✅ | | ✅ | |

> See the [Channels overview](docs/channels/index.mdx) for setup details.

*The desktop client is the entry point for chat, models, channels, skills, memory, and more.*

<br/>

## 🧠 Memory & Knowledge Base

**Long-term memory** uses a three-tier architecture: conversation context (short-term) → daily memory (mid-term) → MEMORY.md (long-term). A nightly **Deep Dream** pass distills scattered memories into refined long-term entries and a narrative journal. See [Long-term Memory](docs/memory/index.mdx) · [Deep Dream](docs/memory/deep-dream.mdx).

**Personal knowledge base** complements the time-ordered memory by organizing structured knowledge **by topic**. The Agent automatically curates valuable information from conversations, maintains cross-references and indexes, and the desktop client offers an interactive knowledge-graph view. See [Personal Knowledge Base](docs/knowledge/index.mdx).

<br/>

## 🔧 Tools & Skills

**Tools** are atomic capabilities the Agent uses to interact with system resources. **Skills** are higher-level workflows defined by a manifest file that compose multiple tools to accomplish complex tasks.

### Tool System

**Built-in tools** cover file I/O (`read` / `write` / `edit` / `ls`), terminal (`bash`), file sending (`send`), memory retrieval (`memory`), environment variables (`env_config`), web fetching (`web_fetch`), scheduling (`scheduler`), web search (`web_search`), vision (`vision`), and browser automation (`browser`).

**MCP protocol** integrates the open ecosystem of [Model Context Protocol](https://modelcontextprotocol.io) servers. A single `mcp.json` is enough — supports stdio / SSE transports, hot reload, and zero-code integration.

Learn more: [Tools overview](docs/tools/index.mdx) · [MCP integration](docs/tools/mcp.mdx).

### Skills System

- **[skill广场](https://www.skill-marketplace.com/)** — browse, search, and install skills in one click
- **GitHub / ClawHub / URL and more** — install skills from any source
- **Conversational authoring** — generate custom skills through dialogue with `skill-creator`; turn any workflow or third-party API into a reusable skill

```bash
/skill list                   # list installed skills
/skill search <keyword>        # search the marketplace
/skill install <name>          # one-click install
```

Learn more: [Skills overview](docs/skills/index.mdx) · [Creating Skills](docs/skills/create.mdx).

<br/>

## 🏷 Changelog

> **2026.09.07:** [v0.0.1](https://github.com/starpickerr/Stella/releases/tag/v0.0.1) — First Stella test release. Desktop updates prompt you to download a GitHub Release (macOS `.dmg` only). Product version lives in the repo-root `VERSION` file.

How to publish a desktop build: see [desktop/README.md](desktop/README.md#version-numbers). Full notes: [Release Notes](docs/releases/overview.mdx)

<br/>

## 🛠️ Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development and contribution instructions.

## ⚠️ Disclaimer

1. This project is licensed under the [MIT License](LICENSE). You are responsible for complying with applicable laws and regulations; the maintainers assume no liability for consequences arising from use of this project.
2. **Cost & safety:** Agent mode consumes substantially more tokens than regular chat. Stella can access the local operating system — only deploy it in trusted environments.

## 📌 Origin

Stella is a personal AI secretary built on an MIT-licensed open-source Agent Harness. Repository: [github.com/starpickerr/Stella](https://github.com/starpickerr/Stella).
