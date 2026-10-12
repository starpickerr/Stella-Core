# Settings Redesign Plan

> **For Stella workers:** Use the project `executing-plans` skill. Steps use checkbox (`- [ ]`) syntax; tests use isolated project data.

**Goal:** Regroup settings by what the user is changing, and make every setting explain itself.

**Architecture:** Settings keeps one page. A left list picks the category; the right side shows grouped rows (label and hint on the left, control on the right). Saving still goes through the existing config, models, briefing, and Apple APIs. No backend change.

**Tech Stack:** React, Playwright.

## Categories

| Key | Name | Contents |
| --- | --- | --- |
| `general` | 通用 | Language, light/dark/system, theme, task notifications, launch at login, web access password |
| `models` | 模型 | Existing models page. The legacy model card is shown only when a product hides the models page |
| `assistant` | 助手 | Context limit, memory turns, step limit, deep thinking, sub-agents, self-evolution, course file saving |
| `connections` | 连接 | Apple Calendar and Apple Reminders |
| `briefing` | 简报 | Existing briefing settings |
| `about` | 关于 | Version, update status, documentation, GitHub, feedback |

Old links keep working: `tab=basic` opens 通用, `tab=integrations` opens 连接.

## Global Constraints

- Theme and language live only in 通用. About no longer repeats them.
- Every row says what it changes. Buttons say what happens.
- Use theme tokens only, so user themes still apply.
- Return-to-origin button and `section=` focus keep working.

## Tasks

- [x] Browser test `tests/ui_settings_redesign.py`: six categories in order, old tab keys redirect, 通用 shows appearance and language, 关于 shows version, update status and three described links, and does not show theme or language. Confirm FAIL.
- [x] Add row and group primitives; split `BasicSettings` into 通用, 助手 and the legacy model card; rewrite About.
- [x] Left category list in `SettingsPage`; drop duplicate inner headings in Apple and briefing panels; point calendar and todo links at `tab=connections`.
- [x] Update existing UI tests that named the old tabs. Run the new test, existing settings tests, and `quality_check.py incremental`.
