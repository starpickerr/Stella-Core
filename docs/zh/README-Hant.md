<p align="center"><img src="../images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](../../README.md) · [中文](README.md) · [繁體中文](README-Hant.md) · [日本語](../ja/README.md)

Stella 是桌面 AI 私人助理，整合對話、事務、日程、帳單和簡報。Electron 客戶端與專用 Python 後端在本機執行。

本專案基於 zhayujie 及貢獻者開發的 [CowAgent](https://github.com/zhayujie/CowAgent)（原 `chatgpt-on-wechat`）獨立開發，沿用上游的 Agent、模型、工具、技能、記憶和訊息通道基礎。Stella 增加桌面工作流程，以及事務、日程、帳單、簡報和安全管理等共用業務服務。來源與版權見[第三方聲明](../../THIRD_PARTY_NOTICES.md)及 [MIT 授權](../../LICENSE)。

## 主要功能

- 設定模型廠商和自訂廠商，為支援的能力分別選擇模型。
- 管理事務、日程、帳單，以及從信箱和 eLearning 收集的資訊。
- 按使用者設定的時間執行自動化，查看執行紀錄，並透過已設定通道投遞結果。
- 管理工具、技能、MCP、記憶、知識庫和外部訊息連線。
- 在安全中心管理全域、專案和對話權限。

## 開始使用

可用安裝包見 [GitHub Releases](https://github.com/starpickerr/Stella/releases)。從最新原始碼執行需要 **Python 3.10+** 和 **Node.js 22.13+**；macOS 另需 Xcode 命令列工具（`xcode-select --install`）。

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows 命令、瀏覽器準備、首次設定及本機資料說明見[使用指南](guide-Hant.md)。介面熱更新使用 `npm --prefix desktop run dev:hot`。

## 文件與開發

- [使用指南](guide-Hant.md)：安裝、設定與日常使用。
- [文件索引](../README.md)：目前架構、業務模組和安全邊界。
- [桌面開發](../../desktop/README.md)：建置和打包。
- [貢獻指南](../../CONTRIBUTING.md)：開發環境與檢查；從 `develop` 開始修改，`main` 用於發布。
- [問題回報](https://github.com/starpickerr/Stella/issues)：分享日誌前，請刪除憑據和個人資訊。

模型呼叫可能產生廠商費用。工具可以存取本機檔案和外部服務，請先設定權限。本機資料可能包含憑據和個人資訊，不要提交至公開倉庫。
