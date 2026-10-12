# Stella 使用指南

[English](../guide.md) · [中文](guide.md) · [繁體中文](guide-Hant.md) · [日本語](../ja/guide.md)

## 安装与启动

可用安装包见 [GitHub Releases](https://github.com/starpickerr/Stella/releases)。桌面安装包会自动启动内置后端。从源码运行需要 Python 3.10+、Node.js 22.13+；macOS 还需要 Xcode 命令行工具（`xcode-select --install`）。

克隆仓库后，在仓库根目录运行：

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

浏览器自动化需要可用的浏览器。安装开发检查使用的 Chromium：`.venv/bin/python -m playwright install chromium`；Windows 使用 `.venv\Scripts\python.exe -m playwright install chromium`。

Electron 启动本机 `127.0.0.1` 专用后端，并将实际端口交给界面。配置通过桌面客户端完成。开发时界面热更新使用 `npm --prefix desktop run dev:hot`。

## 首次配置

1. 打开设置中的模型页，添加厂商和凭据，选择对话模型。自定义厂商填写易识别的名称、接口地址、凭据及厂商提供的模型 ID。
2. 按需要为图像理解、图像生成、语音或向量等能力选择模型；具体支持情况取决于厂商与模型。
3. 打开安全中心，选择工作所需权限。全局默认、项目和单独会话可以使用不同权限。
4. 开始对话。需要时再接入外部服务；消息连接凭据与模型凭据分别配置。

## 日常使用

| 页面 | 用途 |
| --- | --- |
| 对话 | 聊天、附件、执行步骤与工作区上下文 |
| 事务 | 事项、计划日期、截止日期、清单与完成状态 |
| 日程 | 事件、时间与可用的日历集成 |
| 账单 | 账本、支出、收入与报表 |
| 简报 | 配置邮箱/eLearning 来源、收集变化，并确认与事务或日程的关联 |
| 自动化 | 创建定时任务、启停、选择投递目标并查看执行记录 |
| 技能／记忆／知识库 | 管理可复用流程与保留的信息 |
| 安全 | 查看权限、已连接服务、凭据、活动记录与隐私设置 |

简报由手动请求或用户创建的定时任务触发。名称和运行时间由用户决定。阅读简报不会完成事务；写入事务和日程遵循对应的确认及处理规则。

尚未执行或结果待核查的输入可能出现在恢复提示中。请先检查已有结果，再复制重试。主动关闭后，同一会话及其后续保存输入都不会再次显示此提示，底层运行记录仍保留。

## 数据与更新

配置和运行状态默认保存在 `~/.stella`，Agent 工作区使用配置的路径。这些目录可能包含凭据和个人信息。迁移或修改存储前请先备份；卸载客户端不会自动删除它们。

安装版发现更新后会提供 GitHub 下载页。从源码更新时，拉取所需分支，重新安装依赖并运行 `npm --prefix desktop ci`，然后启动客户端。安装版与源码版默认共用本地数据，启动其中一个会替换此前运行的桌面实例。

更多说明：[开发文档](../README.md)、[权限边界](../security-permission-modes.md)、[项目来源](../../THIRD_PARTY_NOTICES.md)。
