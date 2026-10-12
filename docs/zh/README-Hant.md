<p align="center"><img src= "../images/logo.jpg" alt="Stella" width="420" /></p>

<p align="center">
  <a href="https://github.com/starpickerr/Stella/releases/latest"><img src="https://img.shields.io/github/v/release/starpickerr/Stella?cacheSeconds=3600" alt="Latest release" /></a>
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" /></a>
  <a href="https://github.com/starpickerr/Stella"><img src="https://img.shields.io/github/stars/starpickerr/Stella?style=flat-square&cacheSeconds=3600" alt="Stars" /></a>
  <a href="https://github.com/starpickerr/Stella/tree/main/docs"><img src="https://img.shields.io/badge/%E6%96%87%E6%A1%A3-Stella-blue?style=flat&logo=readthedocs&logoColor=white" alt="文件" /></a>
  <a href="https://github.com/starpickerr/Stella/issues"><img src="https://img.shields.io/badge/%E7%A4%BE%E5%8D%80-GitHub-2F93F0?style=flat&logo=github&logoColor=white" alt="社區" /></a>
</p>

<p align="center">
[<a href="../../README.md">English</a>] | [<a href="README.md">中文</a>] | [繁體中文] | [<a href="../ja/README.md">日本語</a>]
</p>

**Stella** 是一個開源的超級 AI 助理，能夠主動思考和規劃任務、操作電腦和外部資源、創造和執行 Skills、構建知識庫與長期記憶、透過自主進化與你一同成長，是 Agent Harness 工程的最佳實踐之一。

Stella 輕量、易部署、可擴充，自由接入主流大模型，透過桌面客戶端連接微信、飛書、釘釘、企微、QQ、Telegram、Slack 等渠道，在個人電腦上執行。

<p align="center">
  <a href="https://github.com/starpickerr/Stella">🐙 GitHub</a> &nbsp;·&nbsp;
  <a href="https://github.com/starpickerr/Stella/tree/main/docs">📖 文件中心</a> &nbsp;·&nbsp;
  <a href="guide/quick-start.mdx">🚀 快速開始</a> &nbsp;·&nbsp;
  <a href="https://www.skill-marketplace.com/">🧩 skill廣場</a> &nbsp;·&nbsp;
  <a href="https://github.com/starpickerr/Stella/releases">💻 下載客戶端</a> &nbsp;·&nbsp;
</p>

<br/>

## 🌟 核心能力

| 能力 | 說明 |
| :--- | :--- |
| [任務規劃](intro/architecture.mdx) | 理解複雜任務並自主分解執行，迴圈呼叫工具直到完成目標 |
| [長期記憶](memory/index.mdx) | 三層記憶架構（上下文 → 天級 → 核心），夢境蒸餾自動整理，支援關鍵詞與向量混合檢索 |
| [知識庫](knowledge/index.mdx) | 自動整理結構化知識為 Markdown Wiki，構建持續增長的知識圖譜，視覺化瀏覽 |
| [自主進化](memory/self-evolution.mdx) | 自動覆盤對話，最佳化技能、處理未完成事項、沉澱記憶與知識，在使用中持續成長 |
| [技能](skills/index.mdx) | 從 [skill廣場](https://www.skill-marketplace.com/)、GitHub、ClawHub 等一鍵安裝；也可透過對話創造自定義技能 |
| [工具](tools/index.mdx) | 內建檔案讀寫、終端、瀏覽器、定時任務、記憶檢索、聯網搜尋等 10+ 工具，支援 MCP 協議 |
| [通道](channels/index.mdx) | 一個 Agent 同時接入桌面客戶端、微信、飛書、釘釘、企微、QQ、公眾號、Telegram、Slack 等多個渠道 |
| 多模態 | 文字、圖片、語音、檔案全訊息型別支援，覆蓋識別、生成、收發 |
| [模型](models/index.mdx) | DeepSeek、Claude、Gemini、GPT、GLM、Qwen、Kimi、MiniMax、Doubao 等主流廠商，設定一行切換 |
| [部署](guide/quick-start.mdx) | Electron 桌面客戶端與專用本地後端 |

<br/>

## 🏗️ 架構總覽

Stella 是一個完整的 **Agent Harness**：訊息從各類**通道**進入，**Agent Core** 結合記憶、知識庫與可用工具/技能進行任務規劃與決策，呼叫**模型**生成結果，再回傳至原通道。各模組解耦清晰，按需擴充。

詳見 [專案架構](intro/architecture.mdx)。

<br/>

## 🚀 快速開始

從 [GitHub Releases](https://github.com/starpickerr/Stella/releases/latest) 下載並開啟 Electron 桌面客戶端。開發者可從原始碼執行：

需要 Python 3.9+ 和 Node.js 22.13+。Windows 命令見[原始碼建置](guide/manual-install.mdx)。

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
cd desktop
npm run dev
```

`npm run dev` 每次都會建置目前介面並啟動桌面專用後端。詳見[快速開始](guide/quick-start.mdx)與[原始碼建置](guide/manual-install.mdx)。

<br/>

## 🤖 模型支援

Stella 支援國內外主流廠商的大語言模型。**文字對話、影像理解、影像生成、語音識別/合成、向量** 等能力均可獨立設定廠商。

| 廠商 | 文字 | 影像理解 | 影像生成 | 語音識別 | 語音合成 | 向量 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](models/deepseek.mdx) | ✅ | | | | | |
| [Claude](models/claude.mdx) | ✅ | ✅ | | | | |
| [OpenAI](models/openai.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](models/gemini.mdx) | ✅ | ✅ | ✅ | | | |
| [MiniMax](models/minimax.mdx) | ✅ | ✅ | ✅ | | ✅ | |
| [智譜 GLM](models/glm.mdx) | ✅ | ✅ | | ✅ | | ✅ |
| [通義千問](models/qwen.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](models/kimi.mdx) | ✅ | ✅ | | | | |
| [豆包 Doubao](models/doubao.mdx) | ✅ | ✅ | ✅ | | | ✅ |
| [百度ERNIE](models/qianfan.mdx) | ✅ | ✅ | | | | |
| [小米 MiMo](models/mimo.mdx) | ✅ | ✅ | | | ✅ | |
| [LinkAI](models/linkai.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [自定義](models/custom.mdx) | ✅ | | | | | |

> 推薦透過 桌面客户端線上設定，無需手動編輯檔案。手動設定請參考各廠商文件，詳見 [模型概覽](models/index.mdx)。

<br/>

## 💬 通道接入

一個 Agent 例項可同時接入多個渠道，啟動時透過 `channel_type` 切換或並行執行。

| 通道 | 文字 | 圖片 | 檔案 | 語音 | 群聊 |
| --- | :-: | :-: | :-: | :-: | :-: |
| [桌面客户端](guide/desktop.mdx)（預設） | ✅ | ✅ | ✅ | ✅ | |
| [微信](channels/weixin.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [飛書](channels/feishu.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [釘釘](channels/dingtalk.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [企微智慧機器人](channels/wecom-bot.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](channels/qq.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [企業微信應用](channels/wecom.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [微信客服](channels/wechat-kf.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [微信公眾號](channels/wechatmp.mdx) | ✅ | ✅ | | ✅ | |
| [Telegram](channels/telegram.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](channels/slack.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](channels/discord.mdx) | ✅ | ✅ | ✅ | | ✅ |

> 飛書、企微智慧機器人支援在桌面客户端內**掃碼一鍵接入**，無需公有 IP。詳見 [通道概覽](channels/index.mdx)。

*桌面客户端是預設通道，也是統一的 Agent 設定和管理入口*

<br/>

## 🧠 記憶與知識庫

**長期記憶**採用三層架構：對話上下文（短期）→ 天級記憶（中期）→ MEMORY.md（長期）。每日自動執行**夢境蒸餾（Deep Dream）**，將分散記憶整合為精煉的長期記憶並生成敘事日記。詳見 [長期記憶](memory/index.mdx) · [夢境蒸餾](memory/deep-dream.mdx)。

**個人知識庫** 與按時間記錄的記憶不同，以**主題為維度**組織結構化知識。Agent 在對話中自動整理有價值資訊，維護交叉引用與索引，桌面客户端可視覺化瀏覽知識圖譜。詳見 [個人知識庫](knowledge/index.mdx)。

<br/>

## 🔧 工具與技能

**工具（Tools）** 是 Agent 作業系統資源的原子能力，**技能（Skills）** 是基於說明檔案的高階工作流，可組合多個工具完成複雜任務。

### 工具系統

**內建工具** 涵蓋檔案讀寫（`read` / `write` / `edit` / `ls`）、終端（`bash`）、檔案傳送（`send`）、記憶檢索（`memory`）、環境變數（`env_config`）、網頁獲取（`web_fetch`）、定時任務（`scheduler`）、聯網搜尋（`web_search`）、影像識別（`vision`）、瀏覽器自動化（`browser`）等常用能力。

**MCP 協議** 透過 [Model Context Protocol](https://modelcontextprotocol.io) 接入開放生態中的各種 MCP 服務，設定一次 `mcp.json` 即用即得，支援 stdio / SSE 協議、熱更新、零程式碼接入。

詳見 [工具概覽](tools/index.mdx) · [MCP 整合](tools/mcp.mdx)。

### 技能系統

- **[skill廣場](https://www.skill-marketplace.com/)** — 瀏覽、搜尋、一鍵安裝
- **GitHub / ClawHub / URL 等** — 任意來源一鍵安裝
- **對話創造** — 透過 `skill-creator` 用對話快速生成自定義技能，可將工作流程或第三方介面直接固化為技能

```bash
/skill list                   # 檢視當前技能
/skill search <關鍵詞>         # 在 skill廣場搜尋
/skill install <名稱>          # 一鍵安裝
```

詳見 [技能概覽](skills/index.mdx) · [建立技能](skills/create.mdx)。

<br/>

## 🏷 更新日誌

> **2026.09.07：** [v0.0.1](https://github.com/starpickerr/Stella/releases/tag/v0.0.1) — Stella 首個測試版。桌面端發現新版本後提示並打開 GitHub Release 手動下載（macOS 只提供 `.dmg`）。產品版本號以倉庫根目錄 `VERSION` 為準。

發版步驟見 [desktop/README.md](../../desktop/README.md)。完整說明：[Release Notes](releases/overview.mdx)

<br/>

## 🔗 相關專案

- **[skill廣場](https://www.skill-marketplace.com/)** — AI Agent 技能市場
- **[bot-on-anything](https://github.com/zhayujie/bot-on-anything)** — 輕量大模型應用框架，支援 Slack、Telegram、Discord、Gmail 等海外平臺
- **[AgentMesh](https://github.com/MinimalFuture/AgentMesh)** — 開源多智慧體（Multi-Agent）框架，透過團隊協同解決複雜問題

<br/>

## 🛠️ 開發與貢獻

歡迎各種形式的貢獻：新功能、Bug 修復、效能最佳化、文件完善，或向 [skill廣場](https://www.skill-marketplace.com/) 分享你的技能。請先閱讀 [CONTRIBUTING.md](../../CONTRIBUTING.md) 瞭解如何開始，然後提交 Issue 討論或直接發起 PR。

歡迎 ⭐ Star 支援專案，並透過 Watch → Custom → Releases 訂閱新版本通知。也歡迎提交 PR、Issue 進行反饋。

## 🌟 貢獻者

![stella contributors](https://contrib.rocks/image?repo=starpickerr/Stella&max=1000)

<br/>

## ⚠️ 宣告

1. 本專案遵循 [MIT 開源協議](../../LICENSE)，主要用於技術研究和學習。使用時請遵守所在地法律法規及相關政策，因使用本專案所產生的一切後果由使用者自行承擔。
2. **成本與安全：** Agent 模式 Token 消耗顯著高於普通對話，請根據效果與成本權衡選擇模型；Agent 具備訪問本地作業系統的能力，請謹慎選擇部署環境。
3. Stella 專案專注於開源技術開發，不會參與、授權或發行任何加密貨幣。

<br/>
