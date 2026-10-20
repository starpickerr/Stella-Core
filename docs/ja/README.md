<p align="center"><img src="../images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](../../README.md) · [中文](../zh/README.md) · [繁體中文](../zh/README-Hant.md) · [日本語](README.md)

**Stella はデスクトップ向けのプライベート AI アシスタント**です。対話を中心に、タスク、予定、請求、スマートブリーフィング、自動化を一つのワークスペースにまとめます。

## 主な機能

### 対話

自然言語で AI とやり取りし、質問への回答、文章作成、情報検索、複雑なタスク実行に対応します。プロジェクトと会話の管理も備えます。

### アプリ

| モジュール | 説明 |
| ---------- | ---- |
| **タスク** | 個人タスクと多階層のサブタスクを管理し、期限・優先度・リマインダーを設定して進捗を追跡。Apple リマインダーとの同期に対応。 |
| **カレンダー** | 予定と時間管理を行い、カレンダー表示・分類・リマインダーを提供。Apple カレンダーとの同期に対応。 |
| **ブリーフィング** | メール、eLearning、予定、タスクをまとめ、重要事項・やること・近い期限を抜き出して個人向けブリーフィングを生成。 |
| **請求** | 収入と支出を記録し、分類・検索・簡単な集計に対応。 |
| **スケジューラ** | 指定した時刻に自動化を実行し、実行履歴を確認し、設定済みメッセージチャネルへ結果を配信。 |

### 情報

| モジュール | 説明 |
| ---------- | ---- |
| **記憶** | AI の長期記憶を管理し、好みや重要な文脈を保存して、より個人に合わせた対話を支援。 |
| **ナレッジ** | 個人ナレッジベースを管理し、保存・検索・引用により AI の情報源を提供。 |

### チャネル

WeChat、Feishu、Telegram などの外部メッセージ基盤を接続・管理し、横断的なやり取りと通知に対応。

### システム

| モジュール | 説明 |
| ---------- | ---- |
| **機能** | AI ツールや Skills などの拡張を確認・管理し、情報取得とタスク実行を強化。 |
| **セキュリティ** | 全体・プロジェクト・会話・バックグラウンドタスクの権限を管理し、ツール呼び出しと機微な操作を制御。セキュリティ活動も確認可能。 |
| **設定** | AI モデルプロバイダー、カスタムモデル、機能ごとのモデル割当、Apple 連携、ブリーフィングなどのアプリ設定を構成。 |
| **ログ** | 実行ログ、エラー、実行記録を確認し、障害調査と稼働状態の把握を支援。 |

## はじめる

### インストーラーを入手

公開済みのインストーラーは [GitHub Releases](https://github.com/starpickerr/Stella/releases) を参照してください。インストール、初回設定、日常の操作は[利用ガイド](guide.md)を参照してください。

### ソースから実行

必要な環境：

- **Python 3.10+**
- **Node.js 22.13+**
- **macOS**：あわせて Xcode Command Line Tools を `xcode-select --install` でインストール。

以下は macOS 向けのコマンドです。Windows のコマンドは[利用ガイド](guide.md)を参照してください。

ローカル開発には Conda の `Stella` 環境（Python 3.12）を使用します。既存の環境がある場合、作成コマンドは省略してください。

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

開発時の UI ホットリロード：

```bash
npm --prefix desktop run dev:hot
```

ブラウザーの準備とローカルデータの説明は[利用ガイド](guide.md)を参照してください。

モデル呼び出しにはプロバイダーの料金が発生する場合があります。ツールはローカルファイルや外部サービスにアクセスできるため、使用前に権限を設定してください。

## ドキュメントと開発

- [利用ガイド](guide.md)：インストール、設定、日常の操作。
- [ドキュメント一覧](../README.md)：構成、業務モジュール、権限の境界。
- [デスクトップ開発](../../desktop/README.md)：ビルドとパッケージ化。
- [コントリビューション](../../CONTRIBUTING.md)：開発環境と検証。開発の基線は `develop`、`main` はリリース用。
- [Issue](https://github.com/starpickerr/Stella/issues)：提出前にログから認証情報と個人情報を削除してください。

## 出典とライセンス

Stella は zhayujie とコントリビューターによる [CowAgent](https://github.com/zhayujie/CowAgent)（旧 `chatgpt-on-wechat`）を基に独自開発されています。上流の Agent、モデル、ツール、Skill、記憶、メッセージ連携を利用し、デスクトップ操作とタスク、カレンダー、請求、ブリーフィング、権限管理の共通サービスを追加しています。

出典と著作権は[第三者表示](../../THIRD_PARTY_NOTICES.md)、ライセンス条項は [MIT ライセンス](../../LICENSE) を参照してください。

## 作者より

これは私が初めて一人で完成させたオープンソースプロジェクトです。開発中の Codex と Cursor の助けに感謝します。まだ改善の余地がありますので、[Issue](https://github.com/starpickerr/Stella/issues) から提案や不具合報告を歓迎します。
