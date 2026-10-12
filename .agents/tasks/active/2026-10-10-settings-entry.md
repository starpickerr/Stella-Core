# Settings Entry Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Move briefing settings into the shared settings page, rename the sidebar entry, and leave only the version and collapse control in the sidebar footer.

**Architecture:** Reuse `SettingsPanel` inside `SettingsPage` as the briefing tab. A return target in navigation state remembers the page that opened settings. Footer theme, language, update, and external links move into settings; logs stay on the existing sidebar item.

**Tech Stack:** React, React Router, Playwright.

**Spec:** `.agents/tasks/active/security-center/requirements.md` section 5.

## Global Constraints

- Sidebar label becomes 设置 / Settings. Existing basic, model, and Apple settings stay.
- Briefing page keeps one button that opens the briefing settings area and no longer renders the form.
- Footer shows only the version and the collapse button, expanded or collapsed.
- Return button appears only when settings was opened from briefing, calendar, or todos, and it survives tab changes.
- Do not move channels, security, capabilities, calendar categories, or task/todo editors into settings.

## Review Focus

- Opening settings from the sidebar or app menu shows no return button.
- Switching from the briefing tab to models and back still returns to the original page and scroll position.
- Product slots that replace the footer menu still do not regain the removed “更多” menu.

---

### Task 1: Settings navigation

**Files:**
- Modify: `desktop/src/renderer/src/pages/SettingsPage.tsx`
- Modify: `desktop/src/renderer/src/pages/BriefingPage.tsx`
- Modify: `desktop/src/renderer/src/pages/CalendarPage.tsx`
- Modify: `desktop/src/renderer/src/pages/TodosPage.tsx`
- Modify: `desktop/src/renderer/src/i18n.ts`
- Test: `tests/ui_settings_entry.py`

- [ ] Write a browser test: sidebar says 设置; briefing button opens the briefing tab without the old in-page form; calendar and todos links show 返回原页面 and return to the source route; a direct sidebar visit has no return button.
- [ ] Run it and confirm FAIL.
- [ ] Add a `briefing` tab that renders the existing panel without its private back button. Pass `{ from, scroll }` in router state.
- [ ] Run the UI test and confirm PASS.
- [ ] Commit.

### Task 2: Footer and about

**Files:**
- Modify: `desktop/src/renderer/src/layout/NavRail.tsx`
- Modify: `desktop/src/renderer/src/pages/SettingsPage.tsx`
- Test: `tests/ui_settings_entry.py`

- [ ] Extend the test: expanded and collapsed footers have no 更多, theme, language, or update controls; those actions exist under settings 关于; logs remain a sidebar item.
- [ ] Run it and confirm FAIL.
- [ ] Replace the footer menu with the version text and collapse button. Move the removed actions into an about section.
- [ ] Run the UI test and confirm PASS.
- [ ] Commit.
