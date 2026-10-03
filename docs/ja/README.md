<p align="center"><img src="../images/logo.jpg" alt="Stella" width="420" /></p>

<p align="center">
  <a href="https://github.com/starpickerr/Stella/releases/latest"><img src="https://img.shields.io/github/v/release/starpickerr/Stella?cacheSeconds=3600" alt="Latest release" /></a>
  <a href="https://github.com/starpickerr/Stella/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT" /></a>
  <a href="https://github.com/starpickerr/Stella"><img src="https://img.shields.io/github/stars/starpickerr/Stella?style=flat-square&cacheSeconds=3600" alt="Stars" /></a>
  <a href="https://github.com/starpickerr/Stella/tree/main/docs"><img src="https://img.shields.io/badge/%E3%83%89%E3%82%AD%E3%83%A5%E3%83%A1%E3%83%B3%E3%83%88-Stella-blue?style=flat&logo=readthedocs&logoColor=white" alt="ドキュメント" /></a>
  <a href="https://github.com/starpickerr/Stella/issues"><img src="https://img.shields.io/badge/Community-GitHub-2F93F0?style=flat&logo=github&logoColor=white" alt="Community" /></a>
  <a href="https://discord.gg/9U8eA8v9TR"><img src="https://img.shields.io/badge/Discord-Join-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord" /></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/25763" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25763" alt="zhayujie%2FStella | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>

<p align="center">
  [<a href="../../README.md">English</a>] | [<a href="../zh/README.md">中文</a>] | [<a href="../zh/README-Hant.md">繁體中文</a>] | [日本語]
</p>

**Stella** は、自律的にタスクを計画し、コンピュータや外部リソースを操作し、Skill を作成・実行し、パーソナルナレッジベースと長期記憶を構築し、自己進化によってユーザーとともに成長するオープンソースのスーパー AI アシスタントです。エンドツーエンドの Agent Harness のリファレンス実装の一つでもあります。

Stella は軽量でデプロイしやすく、拡張性に優れています。主要な LLM プロバイダーをそのまま組み込み、デスクトップクライアントと主要な IM プラットフォームで利用できます。

<p align="center">
  <a href="https://github.com/starpickerr/Stella">🐙 GitHub</a> &nbsp;·&nbsp;
  <a href="intro/index.mdx">📖 ドキュメント</a> &nbsp;·&nbsp;
  <a href="guide/quick-start.mdx">🚀 クイックスタート</a> &nbsp;·&nbsp;
  <a href="https://www.skill-marketplace.com/">🧩 skill広場</a> &nbsp;·&nbsp;
  <a href="https://github.com/starpickerr/Stella/releases">💻 ダウンロード</a> &nbsp;·&nbsp;
  <a href="https://github.com/starpickerr/Stella">☁️ オンラインで試す</a>
</p>

<br/>

## 🎬 デモ

<p align="center">
  <img src="../images/placeholder-video.svg" alt="Stella video placeholder" />
</p>

<br/>

## 🌟 主な機能

| 機能 | 説明 |
| :--- | :--- |
| [タスク計画](intro/architecture.mdx) | 複雑なタスクを分解し、目標達成までツールを繰り返し呼び出して段階的に実行 |
| [長期記憶](memory/index.mdx) | 三層構造（コンテキスト → デイリー → コア）、Deep Dream による自動蒸留、キーワードとベクトルのハイブリッド検索 |
| [ナレッジベース](knowledge/index.mdx) | 構造化された知識を Markdown Wiki として自動整理し、進化し続けるナレッジグラフを可視化ブラウジング |
| [自己進化](memory/self-evolution.mdx) | 会話を自動でレビューして Skill を改善し、未完了のタスクを引き継ぎ、記憶と知識を補完。日々の利用を通じて成長 |
| [Skill](skills/index.mdx) | [skill広場](https://www.skill-marketplace.com/)、GitHub、ClawHub からワンクリックでインストール；対話によるカスタム Skill 作成にも対応 |
| [ツール](tools/index.mdx) | ファイル I/O、ターミナル、ブラウザ、スケジューラ、記憶検索、Web 検索など 10+ の組み込みツール — MCP プロトコルに完全対応 |
| [チャネル](channels/index.mdx) | 一つの Agent でデスクトップクライアント、WeChat、Feishu、DingTalk、WeCom、QQ、公式アカウント、Telegram、Slack を同時にサポート |
| マルチモーダル | テキスト・画像・音声・ファイルをフルサポート — 認識・生成・双方向送受信 |
| [モデル](models/index.mdx) | Claude、GPT、Gemini、DeepSeek、GLM、Qwen、Kimi、MiniMax、Doubao など、設定 1 行で切り替え可能 |
| [デプロイ](guide/quick-start.mdx) | Electron デスクトップクライアントと専用ローカルバックエンド |

<br/>

## 🏗️ アーキテクチャ

<img src="../images/placeholder-image.svg" alt="Stella Architecture" width="750"/>

Stella は完全な **Agent Harness** です：メッセージは各種**チャネル**から流入し、**Agent Core** が記憶・知識・利用可能なツール／Skill を組み合わせてタスクを計画・判断、**モデル**が応答を生成し、結果は元のチャネルに返されます。各レイヤーは疎結合で、独立して拡張可能です。

詳細は [アーキテクチャ](intro/architecture.mdx) を参照してください。

<br/>

## 🚀 クイックスタート

[GitHub Releases](https://github.com/starpickerr/Stella/releases/latest) から Electron デスクトップアプリをダウンロードして起動します。ソースから実行する場合：

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
pip install -r requirements.txt
cd desktop
npm install
npm run dev
```

`npm run dev` は現在の画面を毎回ビルドし、デスクトップ専用バックエンドを起動します。[クイックスタート](guide/quick-start.mdx)と[ソースからビルド](guide/manual-install.mdx)を参照してください。

<br/>

## 🤖 モデル

Stella は主要な LLM プロバイダーすべてに対応しています。**チャット、画像認識、画像生成、ASR/TTS、埋め込み（Embedding）** の各機能はそれぞれ別のベンダーで設定可能です。

| プロバイダー | 代表的なモデル | チャット | 画像認識 | 画像生成 | ASR | TTS | Embedding |
| --- | --- | :-: | :-: | :-: | :-: | :-: | :-: |
| [DeepSeek](models/deepseek.mdx) | deepseek-v4-flash / pro | ✅ | | | | | |
| [Claude](models/claude.mdx) | claude-opus-5 / sonnet-5 | ✅ | ✅ | | | | |
| [OpenAI](models/openai.mdx) | gpt-5.6 シリーズ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Gemini](models/gemini.mdx) | gemini-3.7-flash | ✅ | ✅ | ✅ | | | |
| [MiniMax](models/minimax.mdx) | MiniMax-M3 | ✅ | ✅ | ✅ | | ✅ | |
| [GLM](models/glm.mdx) | glm-5.3、glm-5v-turbo | ✅ | ✅ | | ✅ | | ✅ |
| [Qwen](models/qwen.mdx) | qwen3.8-max | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Kimi](models/kimi.mdx) | kimi-k3 | ✅ | ✅ | | | | |
| [Doubao](models/doubao.mdx) | doubao-seed-2.1 シリーズ | ✅ | ✅ | ✅ | | | ✅ |
| [ERNIE](models/qianfan.mdx) | ernie-5.1 | ✅ | ✅ | | | | |
| [MiMo](models/mimo.mdx) | mimo-v2.5-pro / v2.5 | ✅ | ✅ | | | ✅ | |
| [LinkAI](models/linkai.mdx) | 1 つの Key で 100+ モデルに接続 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| [カスタム](models/custom.mdx) | ローカルモデル / サードパーティプロキシ | ✅ | | | | | |

> デスクトップクライアントでの設定が推奨されており、ファイルを手動編集する必要はありません。手動設定については各プロバイダーのドキュメントおよび [モデル概要](models/index.mdx) を参照してください。

<br/>

## 💬 チャネル

一つの Agent インスタンスで複数のチャネルを同時に提供できます。`channel_type` 設定で切り替えるか、複数のチャネルを並列実行できます。

| チャネル | テキスト | 画像 | ファイル | 音声 | グループ |
| --- | :-: | :-: | :-: | :-: | :-: |
| [デスクトップクライアント](guide/desktop.mdx)（デフォルト） | ✅ | ✅ | ✅ | ✅ | |
| [WeChat](channels/weixin.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [Feishu / Lark](channels/feishu.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [DingTalk](channels/dingtalk.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [WeCom Bot](channels/wecom-bot.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [QQ](channels/qq.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [WeCom App](channels/wecom.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat カスタマーサービス](channels/wechat-kf.mdx) | ✅ | ✅ | ✅ | ✅ | |
| [WeChat 公式アカウント](channels/wechatmp.mdx) | ✅ | ✅ | | ✅ | |
| [Telegram](channels/telegram.mdx) | ✅ | ✅ | ✅ | ✅ | ✅ |
| [Slack](channels/slack.mdx) | ✅ | ✅ | ✅ | | ✅ |
| [Discord](channels/discord.mdx) | ✅ | ✅ | ✅ | | ✅ |

> Feishu と WeCom Bot は **デスクトップクライアント内で QR コードをスキャンするだけで接続**できます — パブリック IP は不要です。詳細は [チャネル概要](channels/index.mdx) を参照してください。

<img src="../images/placeholder-image.svg" alt="Stella desktop client" width="800"/>

*デスクトップクライアントはデフォルトのチャネルであると同時に、Agent の設定・管理を統一的に行う場でもあります。*

<br/>

## 🧠 記憶とナレッジベース

**長期記憶**は三層構造：会話コンテキスト（短期）→ デイリー記憶（中期）→ MEMORY.md（長期）。毎晩の **Deep Dream** が散在する記憶を洗練された長期記憶とナラティブな日記に蒸留します。詳細は [長期記憶](memory/index.mdx) · [Deep Dream](memory/deep-dream.mdx) を参照してください。

**パーソナルナレッジベース**は時系列の記憶とは異なり、構造化された知識を**トピック単位**で整理します。Agent が会話中に有用な情報を自動でキュレーションし、相互参照とインデックスを維持し、デスクトップクライアントでナレッジグラフを可視化できます。詳細は [パーソナルナレッジベース](knowledge/index.mdx) を参照してください。

<table>
  <tr>
    <td width="50%">
      <img src="../images/placeholder-image.svg" alt="長期記憶" />
      <p align="center"><em>長期記憶 · 三層構造 + Deep Dream</em></p>
    </td>
    <td width="50%">
      <img src="../images/placeholder-image.svg" alt="パーソナルナレッジベース" />
      <p align="center"><em>ナレッジベース · 自動キュレーションされた Markdown Wiki</em></p>
    </td>
  </tr>
</table>

<br/>

## 🔧 ツールと Skill

**ツール（Tools）** は Agent がシステムリソースを操作するためのアトミックな機能です。**Skill（Skills）** はマニフェストファイルで定義される高レベルのワークフローで、複数のツールを組み合わせて複雑なタスクを完了します。

### ツールシステム

**組み込みツール**には、ファイル I/O（`read` / `write` / `edit` / `ls`）、ターミナル（`bash`）、ファイル送信（`send`）、記憶検索（`memory`）、環境変数（`env_config`）、Web フェッチ（`web_fetch`）、スケジューラ（`scheduler`）、Web 検索（`web_search`）、画像認識（`vision`）、ブラウザ自動化（`browser`）などが含まれます。

**MCP プロトコル**は [Model Context Protocol](https://modelcontextprotocol.io) のオープンエコシステムを統合します。`mcp.json` を一度設定すれば即利用可能で、stdio / SSE トランスポート、ホットリロード、ノーコード統合をサポートします。

詳細: [ツール概要](tools/index.mdx) · [MCP 統合](tools/mcp.mdx)。

### Skill システム

- **[skill広場](https://www.skill-marketplace.com/)** — 閲覧、検索、ワンクリックインストール
- **GitHub / ClawHub / URL など** — 任意のソースからワンクリックでインストール
- **対話による作成** — `skill-creator` を使って対話でカスタム Skill を生成；ワークフローやサードパーティ API を再利用可能な Skill に変換

```bash
/skill list                   # インストール済み Skill の一覧
/skill search <キーワード>     # マーケットプレイスで検索
/skill install <名前>          # ワンクリックインストール
```

詳細: [Skill 概要](skills/index.mdx) · [Skill 作成](skills/create.mdx)。

<br/>

## 🏷 更新履歴

> **2026.09.07:** [v0.0.1](https://github.com/starpickerr/Stella/releases/tag/v0.0.1) — Stella 最初のテストリリース。デスクトップは GitHub Release への手動ダウンロードを案内します（macOS は `.dmg` のみ）。製品バージョンはリポジトリ直下の `VERSION` です。

公開手順は [desktop/README.md](../../desktop/README.md) を参照。詳細: [リリースノート](releases/overview.mdx)

<br/>

## 🤝 コミュニティとサポート

[**Discord サーバー**](https://discord.gg/9U8eA8v9TR) に参加して、質問や Skill の共有、開発状況の確認ができます：

<a href="https://discord.gg/9U8eA8v9TR"><img src="https://img.shields.io/badge/Discord-コミュニティに参加-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord に参加" /></a>

GitHub で [Issue を報告](https://github.com/starpickerr/Stella/issues) したり、下記 QR コードをスキャンして WeChat コミュニティに参加することもできます：

<img width="130" src="../images/placeholder-image.svg" />

<br/>

## 🔗 関連プロジェクト

- **[skill広場](https://www.skill-marketplace.com/)** — AI エージェント向け Skill マーケットプレイス
- **[bot-on-anything](https://github.com/zhayujie/bot-on-anything)** — 軽量な LLM アプリケーションフレームワーク；Slack、Telegram、Discord、Gmail などに対応
- **[AgentMesh](https://github.com/MinimalFuture/AgentMesh)** — チーム協調による複雑な問題解決のためのオープンソースのマルチエージェントフレームワーク

<br/>

## 🏢 エンタープライズサービス

[**LinkAI**](https://link-ai.tech/) は企業や開発者向けのワンストップ AI Agent プラットフォームで、Stella にマネージドホスティングとエンタープライズグレードのサポートを提供します：

- **🚀 デプロイ不要のホスト型ランタイム** — [Stella オンラインアシスタント](https://github.com/starpickerr/Stella) を 1 分以内に起動、サーバー不要
- **🧠 Agent インフラ** — 主要 LLM・ナレッジベース・データベース・Skill・ワークフローへの統一アクセス。Stella の機能を拡張する、すぐに使えるビルディングブロック
- **🏢 チーム & エンタープライズ機能** — ワークスペース、ロールベースのアクセス制御、監査ログ、本番運用向けプライベートデプロイ

お問い合わせは [GitHub Issues](https://github.com/starpickerr/Stella/issues) をご利用ください。

<br/>

## 🛠️ 開発とコントリビューション

あらゆる形のコントリビューションを歓迎します —— 新機能、バグ修正、パフォーマンス改善、ドキュメント、あるいは [skill広場](https://www.skill-marketplace.com/) への Skill の共有など。まずは [CONTRIBUTING.md](/CONTRIBUTING.md) をご覧いただき、Issue で相談するか、直接 PR を送ってください。

⭐ Star でプロジェクトを応援し、Watch → Custom → Releases で新バージョンの通知を受け取れます。PR や Issue の提出も歓迎します。

## 🌟 コントリビューター

![stella contributors](https://contrib.rocks/image?repo=starpickerr/Stella&max=1000)

<br/>

## ⚠️ 免責事項

1. 本プロジェクトは [MIT License](/LICENSE) に基づき、技術研究と学習を目的としています。利用者は所在地の法令・規制を遵守する必要があり、本プロジェクトの利用に起因するいかなる結果についてもメンテナーは責任を負いません。
2. **コストと安全性：** Agent モードは通常のチャットよりトークン消費が大幅に多いため、品質とコストのバランスを考慮してモデルを選択してください。Agent はローカル OS にアクセスできるため、信頼できる環境にのみデプロイしてください。
3. Stella は純粋なオープンソースプロジェクトであり、暗号通貨の発行・参加・承認は一切行いません。

<br/>

## 📌 プロジェクト改名のお知らせ

本プロジェクトは旧名 `chatgpt-on-wechat` から、2026.04.13 に **Stella** へ正式に改名されました。元の GitHub URL は自動的にリダイレクトされます。既存ユーザーは `git remote set-url origin https://github.com/starpickerr/Stella.git` でローカルのリモートを更新できます。
