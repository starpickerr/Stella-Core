<p align="center"><img src="docs/images/logo.jpg" alt="Stella" width="420" /></p>

<p align="center">
  <a href="https://github.com/starpickerr/Stella/releases/latest"><img src="https://img.shields.io/github/v/release/starpickerr/Stella?cacheSeconds=3600" alt="Latest release"></a>
  <a href="https://github.com/starpickerr/Stella/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <a href="https://github.com/starpickerr/Stella"><img src="https://img.shields.io/github/stars/starpickerr/Stella?style=flat-square&cacheSeconds=3600" alt="Stars"></a>
</p>

<p align="center">
  [English] | [<a href="docs/zh/README.md">中文</a>] | [<a href="docs/zh/README-Hant.md">繁體中文</a>] | [<a href="docs/ja/README.md">日本語</a>]
</p>

**Stella** is a personal AI secretary. It plans tasks, uses your computer and external services, remembers what matters, and grows a private knowledge base — so it can handle everyday work on your behalf across chat, desktop, and messaging apps.

The codebase is an Agent Harness: plug in any major LLM, run it 24/7 on a personal computer or server, and extend it with tools, skills, and channels.

<p align="center">
  <a href="https://github.com/starpickerr/Stella">🐙 GitHub</a> &nbsp;·&nbsp;
  <a href="docs/intro/index.mdx">📖 Docs</a> &nbsp;·&nbsp;
  <a href="docs/guide/quick-start.mdx">🚀 Quick Start</a>
</p>

<br/>

## 🎬 Demo

<p align="center">
  <img src="docs/images/placeholder-video.svg" alt="Stella video placeholder" />
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
| [Channels](docs/channels/index.mdx) | Integrates with Web, WeChat, Feishu, DingTalk, WeCom, QQ, Official Accounts, Telegram, and Slack |
| Multimodal | First-class support for text, images, voice, and files — recognition, generation, and delivery |
| [Models](docs/models/index.mdx) | Claude, GPT, Gemini, DeepSeek, Qwen, GLM, Kimi, MiniMax, Doubao, and more — swap providers from the Web console with one click |
| [Deploy](docs/guide/quick-start.mdx) | One-line installer, unified Web console, multiple deployment modes (local, Docker, server) |

<br/>

## 🏗️ Architecture

<img src="docs/images/placeholder-image.svg" alt="Stella Architecture" width="750"/>

Stella is a complete **Agent Harness**: messages flow in through **Channels**; the **Agent Core** plans and reasons over memory, knowledge, and the available tools and skills; **Models** generate the response, which is sent back through the originating channel. Every layer is decoupled and independently extensible.

Read more in [Architecture](docs/intro/architecture.mdx).

<br/>

## 🚀 Quick Start

Clone this repository, install dependencies, and start Stella:

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
pip install -r requirements.txt
pip install -e .
stella start
```

**Docker:**

```bash
docker compose -f docker/docker-compose.yml up -d
```

Once started, open `http://localhost:9899` to access the **Web console** — chat with Stella, configure models, connect channels, and install skills.

> Deploying on a server? Set `web_host` to `0.0.0.0` in `config.json` to make the console reachable from outside, and set `web_password` to protect it. Don't forget to open port `9899` in your firewall or security group.

> 📖 Guides in this repo: [Quick Start](docs/guide/quick-start.mdx) · [Install from Source](docs/guide/manual-install.mdx) · [Upgrade](docs/guide/upgrade.mdx)

Manage the service with the `stella` CLI:

```bash
stella start | stop | restart        # service control
stella status | logs                  # status and logs
stella update                         # pull latest code and restart
stella skill install <name>           # install a skill
stella install-browser                # install browser automation
```

<br/>

## 🤖 Models

Stella supports all mainstream LLM providers. **Chat, vision, image generation, ASR/TTS, and embeddings** can each be routed to a different vendor. Providers are configured directly in the Web console — no manual file editing required.

| Provider | Featured Models | Chat | Vision | Image Gen | ASR | TTS | Embedding |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](docs/models/deepseek.mdx) | deepseek-v4-flash / pro | ✅ | | | | | |
| [Claude](docs/models/claude.mdx) | claude-opus-5 / sonnet-5 | ✅ | ✅ | | | | |
| [OpenAI](docs/models/openai.mdx) | gpt-5.6 series | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](docs/models/gemini.mdx) | gemini-3.7-flash | ✅ | ✅ | ✅ | | | |
| [MiniMax](docs/models/minimax.mdx) | MiniMax-M3 | ✅ | ✅ | ✅ | | ✅ | |
| [GLM](docs/models/glm.mdx) | glm-5.3, glm-5v-turbo | ✅ | ✅ | | ✅ | | ✅ |
| [Qwen](docs/models/qwen.mdx) | qwen3.8-max | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](docs/models/kimi.mdx) | kimi-k3 | ✅ | ✅ | | | | |
| [Doubao](docs/models/doubao.mdx) | doubao-seed-2.1 series | ✅ | ✅ | ✅ | | | ✅ |
| [ERNIE](docs/models/qianfan.mdx) | ernie-5.1 | ✅ | ✅ | | | | |
| [MiMo](docs/models/mimo.mdx) | mimo-v2.5 / pro | ✅ | ✅ | | | ✅ | |
| [LinkAI](docs/models/linkai.mdx) | One key for 100+ models | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Custom](docs/models/custom.mdx) | Local models / third-party proxy | ✅ | | | | | |

> For details on each provider, see the [Models overview](docs/models/index.mdx).

<br/>

## 💬 Channels

A single Agent instance can serve multiple channels in parallel. Most channels can be onboarded right from the Web console.

| Channel | Text | Image | File | Voice | Group |
| --- | :-: | :-: | :-: | :-: | :-: |
| [Web Console](docs/channels/web.mdx) (default) | ✅ | ✅ | ✅ | ✅ | |
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

<img src="docs/images/placeholder-image.svg" alt="Stella Web Console" width="800"/>

*The Web console is the default channel and the unified entry point to configure models, channels, skills, memory, and more.*

<br/>

## 🧠 Memory & Knowledge Base

**Long-term memory** uses a three-tier architecture: conversation context (short-term) → daily memory (mid-term) → MEMORY.md (long-term). A nightly **Deep Dream** pass distills scattered memories into refined long-term entries and a narrative journal. See [Long-term Memory](docs/memory/index.mdx) · [Deep Dream](docs/memory/deep-dream.mdx).

**Personal knowledge base** complements the time-ordered memory by organizing structured knowledge **by topic**. The Agent automatically curates valuable information from conversations, maintains cross-references and indexes, and the Web console offers an interactive knowledge-graph view. See [Personal Knowledge Base](docs/knowledge/index.mdx).

<table>
  <tr>
    <td width="50%">
      <img src="docs/images/placeholder-image.svg" alt="Long-term Memory" />
      <p align="center"><em>Long-term Memory · Three-tier architecture + Deep Dream</em></p>
    </td>
    <td width="50%">
      <img src="docs/images/placeholder-image.svg" alt="Personal Knowledge Base" />
      <p align="center"><em>Knowledge Base · Auto-curated Markdown wiki</em></p>
    </td>
  </tr>
</table>

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

How to publish a desktop build: see [desktop/README.md](desktop/README.md#publish-a-github-release-v001-and-later). Full notes: [Release Notes](docs/releases/overview.mdx)

<br/>

## 🛠️ Development

See [CONTRIBUTING.md](/CONTRIBUTING.md). The remote for this project is:

```bash
git remote set-url origin https://github.com/starpickerr/Stella.git
```

## ⚠️ Disclaimer

1. This project is licensed under the [MIT License](/LICENSE). You are responsible for complying with applicable laws and regulations; the maintainers assume no liability for consequences arising from use of this project.
2. **Cost & safety:** Agent mode consumes substantially more tokens than regular chat. Stella can access the local operating system — only deploy it in trusted environments.

## 📌 Origin

Stella is a personal AI secretary built on an MIT-licensed open-source Agent Harness. Repository: [github.com/starpickerr/Stella](https://github.com/starpickerr/Stella).
