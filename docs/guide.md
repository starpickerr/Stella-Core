# Stella user guide

[English](guide.md) · [中文](zh/guide.md) · [繁體中文](zh/guide-Hant.md) · [日本語](ja/guide.md)

## Install and launch

Available packaged builds are listed in [GitHub Releases](https://github.com/starpickerr/Stella/releases). A packaged desktop app starts its bundled backend automatically. For source builds, install Python 3.10+ and Node.js 22.13+; on macOS also install Xcode Command Line Tools (`xcode-select --install`).

Clone the repository, enter its root, and run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

Browser automation also needs a supported browser. For the Chromium used by development checks, run `.venv/bin/python -m playwright install chromium` (Windows: `.venv\Scripts\python.exe -m playwright install chromium`).

The client starts a private backend on `127.0.0.1` and receives its actual port from Electron. Use the desktop app to configure it. For UI hot reload, use `npm --prefix desktop run dev:hot`.

## First-run configuration

1. Open Settings → Models. Add a provider and its credentials, then choose a chat model. For custom providers, enter a recognizable name, API endpoint, credentials and the model ID supplied by the provider.
2. Choose additional models for supported capabilities such as vision, image generation, speech or embeddings as needed. Availability depends on the provider and model.
3. Open the Security Center and select the permissions for your work. Global defaults, projects and individual conversations can have different permissions.
4. Start a conversation. Add external connections only when needed; connection credentials are configured separately from model credentials.

## Everyday use

| Page | Purpose |
| --- | --- |
| Chat | Conversations, attachments, execution steps and workspace context |
| Tasks | Work items, planned dates, deadlines, lists and completion |
| Calendar | Events, times and available calendar integrations |
| Bills | Accounts, expenses, income and reports |
| Briefing | Configure email/eLearning sources, collect changes, and confirm links to tasks or events |
| Automation | Create schedules, enable or disable them, choose delivery targets and inspect run history |
| Skills / Memory / Knowledge | Manage reusable workflows and retained information |
| Security | Review permissions, connected services, credentials, activity and privacy controls |

Briefings run when you request them or through schedules you create. Give a schedule any name and time you need. Reading a briefing does not complete a task; task and calendar writes follow their confirmation and handling rules.

An input saved before execution or requiring review can appear in a recovery notice. Check existing results before copying it to retry. Dismissing the notice hides it for that conversation, including future saved inputs; it does not delete the underlying run records.

## Local data and updates

Configuration and runtime state default to `~/.stella`; Agent workspaces use their configured paths. Credentials and personal data can be stored there. Back up these directories before migration or storage changes. Uninstalling the app does not automatically remove them.

The installed app offers the GitHub download page when an update is available. For source updates, pull the desired branch, install requirements again, run `npm --prefix desktop ci`, then launch the client. Source and installed launches share the default local data store; launching one replaces the previous desktop instance.

See [developer documentation](README.md), [permission boundaries](security-permission-modes.md), and [source attribution](../THIRD_PARTY_NOTICES.md).
