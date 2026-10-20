<p align="center"><img src="../images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](../../README.md) · [中文](README.md) · [繁體中文](README-Hant.md) · [日本語](../ja/README.md)

**Stella 是一款桌面端私人 AI 助理**，以智慧對話為核心，將事務、日程、帳單、智慧簡報和自動化任務集中在一個工作空間中。

## 主要功能

### 對話

透過自然語言與 AI 互動，支援問題解答、內容創作、資訊檢索和複雜任務執行，並提供專案與會話管理。

### 應用

| 模組 | 功能說明 |
| ---- | -------- |
| **事務** | 管理個人事務及多級子事務，設定截止時間、優先級和提醒，追蹤進展，支援與 Apple 提醒事項同步。 |
| **日程** | 管理日程與時間安排，提供日曆檢視、分類和提醒，支援與 Apple 日曆同步。 |
| **簡報** | 彙總信箱、eLearning、日程和事務資訊，提取重要事項、待辦任務及臨近截止時間，產生個人化智慧簡報。 |
| **帳單** | 記錄收入與支出，支援帳單分類、查詢和統計分析。 |
| **定時** | 管理自動化任務，按指定時間執行，查看執行紀錄，並透過已設定的訊息通道推送結果。 |

### 資訊

| 模組 | 功能說明 |
| ---- | -------- |
| **記憶** | 管理 AI 長期記憶，保存使用者偏好和重要上下文，支援個人化互動。 |
| **知識** | 管理個人知識庫，支援知識儲存、檢索和引用，為 AI 提供知識來源。 |

### 通道

連接和管理微信、飛書、Telegram 等外部訊息平台，支援跨平台互動與訊息通知。

### 系統

| 模組 | 功能說明 |
| ---- | -------- |
| **能力** | 查看和管理 AI 工具、Skills 等擴充能力，增強資訊取得與任務執行能力。 |
| **安全** | 管理全域、專案、會話及背景任務權限，控制工具呼叫和敏感操作，查看安全活動。 |
| **設定** | 設定 AI 模型廠商、自訂模型、模型能力分配、Apple 整合、簡報及其他應用設定。 |
| **日誌** | 查看執行日誌、錯誤資訊和執行紀錄，輔助故障排除與執行狀態分析。 |

## 開始使用

### 下載安裝包

可用安裝包見 [GitHub Releases](https://github.com/starpickerr/Stella/releases)。安裝、首次設定及日常使用見[使用指南](guide-Hant.md)。

### 從原始碼執行

環境要求：

- **Python 3.10+**
- **Node.js 22.13+**
- **macOS**：還需安裝 Xcode 命令列工具，執行 `xcode-select --install`。

以下命令適用於 macOS；Windows 命令見[使用指南](guide-Hant.md)。

本機開發統一使用 Conda 的 `Stella` 環境（Python 3.12）；已有環境時略過建立命令。

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

開發時啟用介面熱更新：

```bash
npm --prefix desktop run dev:hot
```

瀏覽器準備和本機資料說明見[使用指南](guide-Hant.md)。

模型呼叫可能產生廠商費用。工具可以存取本機檔案和外部服務，使用前請先設定權限。

## 文件與開發

- [使用指南](guide-Hant.md)：安裝、設定與日常使用。
- [文件索引](../README.md)：架構、業務模組與安全邊界。
- [桌面開發](../../desktop/README.md)：建置和打包。
- [貢獻指南](../../CONTRIBUTING.md)：開發環境與檢查要求；開發以 `develop` 為基線，`main` 用於發布。
- [問題回報](https://github.com/starpickerr/Stella/issues)：提交問題前，請從日誌中刪除憑據和個人資訊。

## 專案來源與授權

Stella 基於 zhayujie 及貢獻者開發的 [CowAgent](https://github.com/zhayujie/CowAgent)（原 `chatgpt-on-wechat`）獨立開發，沿用上游的 Agent、模型、工具、技能、記憶和訊息通道基礎，並增加桌面工作流程，以及事務、日程、帳單、簡報和安全管理等共用業務服務。

來源與版權說明見[第三方聲明](../../THIRD_PARTY_NOTICES.md)，授權條款見 [MIT 授權](../../LICENSE)。

## 作者的話

這是我第一次獨立完成的開源專案，感謝 Codex 和 Cursor 在開發過程中提供的幫助。專案仍有需要完善的地方，歡迎透過[問題回報](https://github.com/starpickerr/Stella/issues)提交建議和缺陷報告。
