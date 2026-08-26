<p align="center"><img src="https://github.com/user-attachments/assets/eca9a9ec-8534-4615-9e0f-96c5ac1d10a3" alt="Stella" width="420" /></p>

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
  <video src="https://github.com/user-attachments/assets/8625a19f-615c-4343-8be8-3707ce4d4d4e" controls muted playsinline width="720">
    Your browser can't play this video.
    <a href="https://github.com/starpickerr/Stella">Watch the demo in the repository →</a>
  </video>
</p>

<br/>

## 🌟 Highlights

| Capability | Description |
| :--- | :--- |
| [Planning](https://docs.cowagent.ai/intro/architecture) | Decomposes complex tasks and executes them step by step, looping over tools until the goal is reached |
| [Memory](https://docs.cowagent.ai/memory/index) | Three-tier architecture (context → daily → core), automatic Deep Dream distillation, hybrid keyword + vector retrieval |
| [Knowledge](https://docs.cowagent.ai/knowledge/index) | Auto-curates structured knowledge into a Markdown wiki, builds an evolving knowledge graph with visual browsing |
| [Evolution](https://docs.cowagent.ai/memory/self-evolution) | Self-Evolution reviews conversations automatically to improve skills, follow up on unfinished tasks, and consolidate memory and knowledge, growing through everyday use |
| [Skills](https://docs.cowagent.ai/skills/index) | One-click install from [Skill Hub](https://skills.cowagent.ai/), GitHub, ClawHub; or create custom skills via natural-language conversation |
| [Tools](https://docs.cowagent.ai/tools/index) | Built-in file I/O, terminal, browser, scheduler, memory retrieval, web search, and 10+ more tools — with native MCP integration |
| [Channels](https://docs.cowagent.ai/channels/index) | Integrates with Web, WeChat, Feishu, DingTalk, WeCom, QQ, Official Accounts, Telegram, and Slack |
| Multimodal | First-class support for text, images, voice, and files — recognition, generation, and delivery |
| [Models](https://docs.cowagent.ai/models/index) | Claude, GPT, Gemini, DeepSeek, Qwen, GLM, Kimi, MiniMax, Doubao, and more — swap providers from the Web console with one click |
| [Deploy](https://docs.cowagent.ai/guide/quick-start) | One-line installer, unified Web console, multiple deployment modes (local, Docker, server) |

<br/>

## 🏗️ Architecture

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/architecture/en/architecture.png" alt="Stella Architecture" width="750"/>

Stella is a complete **Agent Harness**: messages flow in through **Channels**; the **Agent Core** plans and reasons over memory, knowledge, and the available tools and skills; **Models** generate the response, which is sent back through the originating channel. Every layer is decoupled and independently extensible.

Read more in [Architecture](https://docs.cowagent.ai/intro/architecture).

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
| [DeepSeek](https://docs.cowagent.ai/models/deepseek) | deepseek-v4-flash / pro | ✅ | | | | | |
| [Claude](https://docs.cowagent.ai/models/claude) | claude-opus-5 / sonnet-5 | ✅ | ✅ | | | | |
| [OpenAI](https://docs.cowagent.ai/models/openai) | gpt-5.6 series | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](https://docs.cowagent.ai/models/gemini) | gemini-3.7-flash | ✅ | ✅ | ✅ | | | |
| [MiniMax](https://docs.cowagent.ai/models/minimax) | MiniMax-M3 | ✅ | ✅ | ✅ | | ✅ | |
| [GLM](https://docs.cowagent.ai/models/glm) | glm-5.3, glm-5v-turbo | ✅ | ✅ | | ✅ | | ✅ |
| [Qwen](https://docs.cowagent.ai/models/qwen) | qwen3.8-max | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](https://docs.cowagent.ai/models/kimi) | kimi-k3 | ✅ | ✅ | | | | |
| [Doubao](https://docs.cowagent.ai/models/doubao) | doubao-seed-2.1 series | ✅ | ✅ | ✅ | | | ✅ |
| [ERNIE](https://docs.cowagent.ai/models/qianfan) | ernie-5.1 | ✅ | ✅ | | | | |
| [MiMo](https://docs.cowagent.ai/models/mimo) | mimo-v2.5 / pro | ✅ | ✅ | | | ✅ | |
| [LinkAI](https://docs.cowagent.ai/models/linkai) | One key for 100+ models | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Custom](https://docs.cowagent.ai/models/custom) | Local models / third-party proxy | ✅ | | | | | |

> For details on each provider, see the [Models overview](https://docs.cowagent.ai/models/index).

<br/>

## 💬 Channels

A single Agent instance can serve multiple channels in parallel. Most channels can be onboarded right from the Web console.

| Channel | Text | Image | File | Voice | Group |
| --- | :-: | :-: | :-: | :-: | :-: |
| [Web Console](https://docs.cowagent.ai/channels/web) (default) | ✅ | ✅ | ✅ | ✅ | |
| [Telegram](https://docs.cowagent.ai/channels/telegram) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](https://docs.cowagent.ai/channels/slack) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](https://docs.cowagent.ai/channels/discord) | ✅ | ✅ | ✅ | | ✅ |
| [WeChat](https://docs.cowagent.ai/channels/weixin) | ✅ | ✅ | ✅ | ✅ | |
| [Feishu / Lark](https://docs.cowagent.ai/channels/feishu) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [DingTalk](https://docs.cowagent.ai/channels/dingtalk) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [WeCom Bot](https://docs.cowagent.ai/channels/wecom-bot) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](https://docs.cowagent.ai/channels/qq) | ✅ | ✅ | ✅ | | ✅ |
| [WeCom App](https://docs.cowagent.ai/channels/wecom) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat Customer Service](https://docs.cowagent.ai/channels/wechat-kf) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat Official Account](https://docs.cowagent.ai/channels/wechatmp) | ✅ | ✅ | | ✅ | |

> See the [Channels overview](https://docs.cowagent.ai/channels/index) for setup details.

<img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/en/web-console-chat.png" alt="Stella Web Console" width="800"/>

*The Web console is the default channel and the unified entry point to configure models, channels, skills, memory, and more.*

<br/>

## 🧠 Memory & Knowledge Base

**Long-term memory** uses a three-tier architecture: conversation context (short-term) → daily memory (mid-term) → MEMORY.md (long-term). A nightly **Deep Dream** pass distills scattered memories into refined long-term entries and a narrative journal. See [Long-term Memory](https://docs.cowagent.ai/memory/index) · [Deep Dream](https://docs.cowagent.ai/memory/deep-dream).

**Personal knowledge base** complements the time-ordered memory by organizing structured knowledge **by topic**. The Agent automatically curates valuable information from conversations, maintains cross-references and indexes, and the Web console offers an interactive knowledge-graph view. See [Personal Knowledge Base](https://docs.cowagent.ai/knowledge/index).

<table>
  <tr>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/en/web-console-memory.png" alt="Long-term Memory" />
      <p align="center"><em>Long-term Memory · Three-tier architecture + Deep Dream</em></p>
    </td>
    <td width="50%">
      <img src="https://cdn.jsdelivr.net/gh/zhayujie/cowagent-assets@main/screenshots/en/web-console-knowledge.png" alt="Personal Knowledge Base" />
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

Learn more: [Tools overview](https://docs.cowagent.ai/tools/index) · [MCP integration](https://docs.cowagent.ai/tools/mcp).

### Skills System

- **[Skill Hub](https://skills.cowagent.ai/)** — open skill marketplace: browse, search, install in one click
- **GitHub / ClawHub / URL and more** — install skills from any source
- **Conversational authoring** — generate custom skills through dialogue with `skill-creator`; turn any workflow or third-party API into a reusable skill

```bash
/skill list                   # list installed skills
/skill search <keyword>        # search the marketplace
/skill install <name>          # one-click install
```

Learn more: [Skills overview](https://docs.cowagent.ai/skills/index) · [Creating Skills](https://docs.cowagent.ai/skills/create).

<br/>

## 🏷 Changelog

> **2026.08.20:** [v2.1.7](https://github.com/starpickerr/Stella/releases/tag/2.1.7) — Multiple workspaces, session-level permission modes, task notifications, desktop improvements, plus new model support.

> **2026.08.12:** [v2.1.6](https://github.com/starpickerr/Stella/releases/tag/2.1.6) — Sub agents for parallel task delegation, reasoning-effort settings, a pluggable memory vector backend, plus experience and security improvements.

> **2026.07.29:** [v2.1.5](https://github.com/starpickerr/Stella/releases/tag/2.1.5) — Workspace with file preview, core tool improvements (file search, write-time validation, background commands), context compaction (`/compact`), one-click prompt optimization, security hardening.

> **2026.07.20:** [v2.1.4](https://github.com/starpickerr/Stella/releases/tag/2.1.4) — Desktop experience improvements, MCP OAuth authorization, Lark channel enhancements, scheduler improvements and data backup, new models.

> **2026.07.08:** [v2.1.3](https://github.com/starpickerr/Stella/releases/tag/2.1.3) — Desktop client for macOS / Windows, knowledge base document management, on-demand MCP tool retrieval, Traditional Chinese support, new models.

> **2026.06.18:** [v2.1.2](https://github.com/starpickerr/Stella/releases/tag/2.1.2) — Web console upgrades (scheduled task management, knowledge base categories, multiple custom model providers), Self-Evolution improvements, new models (kimi-k2.7-code, glm-5.2), security hardening and refinements.

> **2026.06.09:** [v2.1.1](https://github.com/starpickerr/Stella/releases/tag/2.1.1) — Self-Evolution, Web console upgrades (message management, parallel sessions), cross-platform MCP enhancements with concurrent calls, new models (MiniMax-M3, qwen3.7-plus), Python 3.13 support.

> **2026.06.01:** [v2.1.0](https://github.com/starpickerr/Stella/releases/tag/2.1.0) — Internationalization, new channels (Telegram, Discord, Slack, WeChat Customer Service), CLI interaction upgrades, streamlined one-line install, MCP Streamable HTTP support, new models (claude-opus-4-8, MiMo).

Full history: [Release Notes](https://docs.cowagent.ai/releases/overview)

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
