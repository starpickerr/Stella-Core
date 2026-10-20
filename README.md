<p align="center"><img src="docs/images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](README.md) · [中文](docs/zh/README.md) · [繁體中文](docs/zh/README-Hant.md) · [日本語](docs/ja/README.md)

**Stella is a private desktop AI assistant** centered on intelligent chat, bringing tasks, calendars, bills, smart briefings, and automation together in one workspace.

## Features

### Chat

Talk with AI in natural language for questions, writing, information lookup, and complex tasks, with project and conversation management.

### Apps

| Module | Description |
| ------ | ----------- |
| **Tasks** | Manage personal tasks and nested subtasks with due dates, priorities, and reminders. Track progress and sync with Apple Reminders. |
| **Calendar** | Manage schedules and time with calendar views, categories, and reminders. Sync with Apple Calendar. |
| **Briefings** | Combine email, eLearning, calendar, and task information to surface important items, to-dos, and upcoming deadlines in a personalized briefing. |
| **Bills** | Record income and expenses with categories, search, and basic analytics. |
| **Health** | Personal health information and analysis — **planned**. |
| **Scheduler** | Manage automation that runs at chosen times, review execution history, and deliver results through configured messaging channels. |

### Information

| Module | Description |
| ------ | ----------- |
| **Memory** | Manage long-term AI memory for preferences and important context, enabling more personal interactions. |
| **Knowledge** | Manage a personal knowledge base with storage, retrieval, and citation so AI can use your sources. |

### Channels

Connect and manage external messaging platforms such as WeChat, Feishu, and Telegram for cross-platform chat and notifications.

### System

| Module | Description |
| ------ | ----------- |
| **Capabilities** | View and manage AI tools, Skills, and other extensions that improve information access and task execution. |
| **Security** | Manage global, project, conversation, and background-task permissions. Control tool calls and sensitive actions, and review security activity. |
| **Settings** | Configure AI model providers, custom models, capability assignment, Apple integrations, briefings, and other app settings. |
| **Logs** | View runtime logs, errors, and execution records for troubleshooting and status checks. |

## Get started

### Download an installer

Available installers are in [GitHub Releases](https://github.com/starpickerr/Stella/releases). For installation, first-run setup, and everyday use, see the [user guide](docs/guide.md).

### Run from source

Requirements:

- **Python 3.10+**
- **Node.js 22.13+**
- **macOS**: also install Xcode Command Line Tools with `xcode-select --install`.

The commands below are for macOS. Windows commands are in the [user guide](docs/guide.md).

Local development uses the Conda `Stella` environment (Python 3.12). Skip environment creation if it already exists.

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

For UI hot reload during development:

```bash
npm --prefix desktop run dev:hot
```

Browser setup and local data details are in the [user guide](docs/guide.md).

Model calls may incur provider charges. Tools can access local files and external services; configure permissions before using them.

## Documentation and development

- [User guide](docs/guide.md): installation, configuration, and everyday use.
- [Documentation index](docs/README.md): architecture, business modules, and security boundaries.
- [Desktop development](desktop/README.md): builds and packaging.
- [Contributing](CONTRIBUTING.md): development setup and checks. Develop from `develop`; `main` is for releases.
- [Issues](https://github.com/starpickerr/Stella/issues): remove credentials and personal data from logs before filing a report.

## Source and license

Stella is independently developed from [CowAgent](https://github.com/zhayujie/CowAgent) (formerly `chatgpt-on-wechat`) by zhayujie and contributors. It reuses the upstream Agent, model, tool, skill, memory, and messaging foundations, and adds desktop workflows plus shared business services for tasks, calendars, bills, briefings, and security management.

See [third-party notices](THIRD_PARTY_NOTICES.md) for source attribution and the [MIT license](LICENSE) for license terms.

## A note from the author

This is the first open-source project I completed on my own. Thanks to Codex and Cursor for help during development. There is still work to do; suggestions and bug reports through [Issues](https://github.com/starpickerr/Stella/issues) are welcome.
