# Stella 利用ガイド

[English](../guide.md) · [中文](../zh/guide.md) · [繁體中文](../zh/guide-Hant.md) · [日本語](guide.md)

## インストールと起動

公開済みのインストーラーは [GitHub Releases](https://github.com/starpickerr/Stella/releases) にあります。パッケージ版は同梱のバックエンドを自動起動します。ソースには Python 3.10+ と Node.js 22.13+、macOS では Xcode Command Line Tools（`xcode-select --install`）も必要です。

リポジトリをクローンし、ルートで実行します。

ローカル開発には Conda の `Stella` 環境（Python 3.12）を使用します。既存の環境がある場合、作成コマンドは省略してください。

```bash
conda create -n Stella python=3.12
conda activate Stella
python -m pip install --upgrade pip setuptools
python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows：

```powershell
conda create -n Stella python=3.12
conda activate Stella
python -m pip install --upgrade pip setuptools
python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

ブラウザー自動化には対応ブラウザーが必要です。開発用 Chromium は `python -m playwright install chromium`、Windows では `python -m playwright install chromium` で準備します。

Electron は `127.0.0.1` の専用バックエンドを起動し、実際のポートを UI に渡します。設定はデスクトップで行います。UI のホットリロードには `npm --prefix desktop run dev:hot` を使います。

## 初回設定

1. 設定のモデルページでプロバイダーと認証情報を登録し、会話モデルを選択します。カスタムプロバイダーには分かりやすい名前、API のアドレス、認証情報、提供されたモデル ID を指定します。
2. 必要に応じて画像認識、画像生成、音声、埋め込みのモデルを設定します。対応する機能はプロバイダーとモデルによって異なります。
3. セキュリティセンターで作業に必要な権限を選択します。全体、プロジェクト、個別の会話に異なる権限を設定できます。
4. 会話を開始します。外部連携は必要なものから追加します。チャネルの認証情報とモデルの認証情報は別々に設定します。

## 日常の操作

| ページ | 用途 |
| --- | --- |
| 会話 | チャット、添付、実行手順、ワークスペースの情報 |
| タスク | 作業、予定日、期限、リスト、完了状態 |
| カレンダー | 予定、時刻、対応するカレンダー連携 |
| 請求 | 帳簿、支出、収入、レポート |
| ブリーフィング | メール/eLearning の設定、変化の収集、タスクや予定との関連付け |
| 自動化 | スケジュール、実行の有効化・無効化、配信先、履歴 |
| Skill／記憶／ナレッジ | 再利用できる手順と保持する情報の管理 |
| セキュリティ | 権限、接続済みサービス、認証情報、履歴、プライバシー |

ブリーフィングは手動の要求または自分で作成したスケジュールで実行します。名前と実行時刻は自由に設定できます。読んだだけではタスクは完了せず、タスクや予定への書き込みにはそれぞれの確認・処理ルールが適用されます。

実行前に保存された入力や結果の確認が必要な入力は、復元の通知に表示される場合があります。再試行する前に既存の結果を確認してください。通知を閉じると、その会話の後続入力についても表示されなくなります。元の実行記録は残ります。

## ローカルデータと更新

設定と実行状態は通常 `~/.stella`、Agent のワークスペースは設定した場所に保存されます。認証情報や個人データを含むため、移行や保存形式の変更前にバックアップしてください。アンインストールしても自動的には削除されません。

パッケージ版は更新が見つかると GitHub のダウンロードページを案内します。ソース版は対象ブランチを取得し、依存関係を再インストールして `npm --prefix desktop ci` を実行してから起動します。ソース版とパッケージ版は既定のデータを共有し、新しい起動は前のデスクトップインスタンスを置き換えます。

[開発ドキュメント](../README.md)、[権限の境界](../security-permission-modes.md)、[プロジェクトの出典](../../THIRD_PARTY_NOTICES.md)も参照してください。
