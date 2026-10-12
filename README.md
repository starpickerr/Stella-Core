<p align="center"><img src="docs/images/logo.jpg" alt="Stella" width="160" /></p>

# Stella

[English](README.md) · [中文](docs/zh/README.md) · [繁體中文](docs/zh/README-Hant.md) · [日本語](docs/ja/README.md)

Stella is a desktop AI assistant for conversations, tasks, calendars, bills, and briefings. It combines an Electron client with a private Python backend on your computer.

Stella is independently developed from [CowAgent](https://github.com/zhayujie/CowAgent), formerly `chatgpt-on-wechat`, by zhayujie and contributors. It builds on the upstream Agent, model, tool, skill, memory, and messaging foundations. Stella adds desktop workflows and shared business services for tasks, calendars, bills, briefings, and security management. See [source attribution](THIRD_PARTY_NOTICES.md) and the [MIT license](LICENSE).

## Features

- Chat with configurable model providers and custom providers; choose models separately for supported capabilities.
- Manage tasks, calendar events, bills, and information collected from email and eLearning.
- Schedule automation at times you choose, with execution history and configured delivery channels.
- Configure tools, skills, MCP services, memory, knowledge, and external messaging connections.
- Manage global, project, and conversation permissions from the Security Center.

## Get started

Find available installers in [GitHub Releases](https://github.com/starpickerr/Stella/releases). For the latest source, use **Python 3.10+** and **Node.js 22.13+**. On macOS, install Xcode Command Line Tools with `xcode-select --install`.

```bash
git clone https://github.com/starpickerr/Stella.git
cd Stella
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -r requirements.txt
npm --prefix desktop ci
npm --prefix desktop run dev
```

Windows commands, browser setup, first-run configuration, and local data details are in the [user guide](docs/guide.md). For UI hot reload, run `npm --prefix desktop run dev:hot`.

## Documentation and development

- [User guide](docs/guide.md): installation, configuration, and everyday use.
- [Documentation index](docs/README.md): architecture, business modules, and security details.
- [Desktop development](desktop/README.md): builds and packaging.
- [Contributing](CONTRIBUTING.md): development setup and checks. Start changes from `develop`; `main` holds releases.
- [Issues](https://github.com/starpickerr/Stella/issues): bug reports and feature requests. Remove credentials and personal data from logs before sharing them.

Model calls may incur provider charges. Tools can access local files and external services; configure permissions before running them. Stella's local storage can contain credentials and personal data, so keep those directories out of public repositories.
