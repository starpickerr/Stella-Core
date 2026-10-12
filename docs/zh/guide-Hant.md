# Stella 使用指南

[English](../guide.md) · [中文](guide.md) · [繁體中文](guide-Hant.md) · [日本語](../ja/guide.md)

## 安裝與啟動

可用安裝包見 [GitHub Releases](https://github.com/starpickerr/Stella/releases)。桌面安裝包會自動啟動內建後端。從原始碼執行需要 Python 3.10+、Node.js 22.13+；macOS 另需 Xcode 命令列工具（`xcode-select --install`）。

複製倉庫後，在倉庫根目錄執行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows 使用：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

瀏覽器自動化需要可用的瀏覽器。安裝開發檢查使用的 Chromium：`.venv/bin/python -m playwright install chromium`；Windows 使用 `.venv\Scripts\python.exe -m playwright install chromium`。

Electron 啟動本機 `127.0.0.1` 專用後端，並將實際連接埠交給介面。設定透過桌面客戶端完成。開發時介面熱更新使用 `npm --prefix desktop run dev:hot`。

## 首次設定

1. 開啟設定中的模型頁，新增廠商和憑據，選擇對話模型。自訂廠商填寫易識別的名稱、介面位址、憑據及廠商提供的模型 ID。
2. 按需要為影像理解、影像生成、語音或向量等能力選擇模型；具體支援情況取決於廠商與模型。
3. 開啟安全中心，選擇工作所需權限。全域預設、專案和個別對話可以使用不同權限。
4. 開始對話。需要時再接入外部服務；訊息連線憑據與模型憑據分別設定。

## 日常使用

| 頁面 | 用途 |
| --- | --- |
| 對話 | 聊天、附件、執行步驟與工作區上下文 |
| 事務 | 事項、計畫日期、截止日期、清單與完成狀態 |
| 日程 | 事件、時間與可用的行事曆整合 |
| 帳單 | 帳本、支出、收入與報表 |
| 簡報 | 設定信箱/eLearning 來源、收集變化，並確認與事務或日程的關聯 |
| 自動化 | 建立排程、啟停、選擇投遞目標並查看執行紀錄 |
| 技能／記憶／知識庫 | 管理可重用流程與保留的資訊 |
| 安全 | 查看權限、已連線服務、憑據、活動紀錄與隱私設定 |

簡報由手動請求或使用者建立的排程觸發。名稱和執行時間由使用者決定。閱讀簡報不會完成事務；寫入事務和日程遵循對應的確認及處理規則。

尚未執行或結果待核查的輸入可能出現在恢復提示中。請先檢查已有結果，再複製重試。主動關閉後，同一對話及其後續儲存輸入都不會再次顯示此提示，底層執行紀錄仍保留。

## 資料與更新

設定和執行狀態預設儲存在 `~/.stella`，Agent 工作區使用設定的路徑。這些目錄可能包含憑據和個人資訊。遷移或修改儲存前請先備份；解除安裝客戶端不會自動刪除它們。

安裝版發現更新後會提供 GitHub 下載頁。從原始碼更新時，拉取所需分支，重新安裝依賴並執行 `npm --prefix desktop ci`，然後啟動客戶端。安裝版與原始碼版預設共用本機資料，啟動其中一個會替換此前執行的桌面實例。

更多說明：[開發文件](../README.md)、[權限邊界](../security-permission-modes.md)、[專案來源](../../THIRD_PARTY_NOTICES.md)。
