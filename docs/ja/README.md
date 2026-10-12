<p align="center"><img src="../images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](../../README.md) · [中文](../zh/README.md) · [繁體中文](../zh/README-Hant.md) · [日本語](README.md)

Stella は会話、タスク、カレンダー、請求管理、ブリーフィングをまとめたデスクトップ AI アシスタントです。Electron クライアントと専用 Python バックエンドがローカルで動作します。

本プロジェクトは zhayujie とコントリビューターによる [CowAgent](https://github.com/zhayujie/CowAgent)（旧 `chatgpt-on-wechat`）を基に独自開発されています。上流の Agent、モデル、ツール、Skill、記憶、メッセージ連携を利用し、Stella のデスクトップ操作とタスク、カレンダー、請求、ブリーフィング、権限管理の共通サービスを追加しています。[出典と著作権](../../THIRD_PARTY_NOTICES.md)、[MIT ライセンス](../../LICENSE)を参照してください。

## 主な機能

- モデルプロバイダーやカスタムプロバイダーを設定し、対応する機能ごとにモデルを選択。
- タスク、予定、請求、およびメールや eLearning から集めた情報を管理。
- 指定した時刻に自動化を実行し、履歴を確認し、設定済みチャネルで結果を配信。
- ツール、Skill、MCP、記憶、ナレッジ、外部メッセージ連携を管理。
- セキュリティセンターで全体、プロジェクト、会話の権限を設定。

## はじめる

公開済みのインストーラーは [GitHub Releases](https://github.com/starpickerr/Stella/releases) を参照してください。最新ソースには **Python 3.10+** と **Node.js 22.13+** が必要です。macOS では Xcode Command Line Tools（`xcode-select --install`）も必要です。

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows のコマンド、ブラウザーの準備、初回設定、ローカルデータは[利用ガイド](guide.md)を参照してください。UI のホットリロードには `npm --prefix desktop run dev:hot` を使います。

## ドキュメントと開発

- [利用ガイド](guide.md)：インストール、設定、日常の操作。
- [ドキュメント一覧](../README.md)：現在の構成、業務モジュール、権限の境界。
- [デスクトップ開発](../../desktop/README.md)：ビルドとパッケージ化。
- [コントリビューション](../../CONTRIBUTING.md)：開発環境と検証。変更は `develop` から始め、`main` はリリース用です。
- [Issue](https://github.com/starpickerr/Stella/issues)：ログを共有する前に認証情報や個人情報を除去してください。

モデルの呼び出しにはプロバイダーの料金が発生する場合があります。ツールはローカルファイルや外部サービスにアクセスできるため、先に権限を設定してください。認証情報や個人データを含むローカル保存先は公開リポジトリに含めないでください。
