# Page Header Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Give every titled built-in page a full-width header and divider while leaving the content width chosen by that page.

**Architecture:** Add one `PageHeader` component. Pages that already have a full-width header keep their content columns. Pages whose title sits inside `max-w-*` move only the title row out.

**Tech Stack:** React, Playwright.

**Spec:** `.agents/task/requirements.md` section 7 and `.agents/task/ui-consistency.md`.

## Global Constraints

- Header and its bottom border span the main content area. Content may stay `max-w-* mx-auto`.
- Chat keeps no page title. Do not add a second line next to the window title bar.
- Do not restyle login, onboarding, dialogs, or plugin product routes beyond using the header when they already have a page title.
- Narrow and collapsed-sidebar layouts must not scroll horizontally.

## Review Focus

- Tasks page title border meets both edges of the main pane while task cards stay inside `max-w-3xl`.
- Security, settings, health, logs, and todos titles are no longer inside the centered column.
- Detail and return bars do not draw a second border against the page header.

---

### Task 1: Header component and the five inset pages

**Files:**
- Create: `desktop/src/renderer/src/components/PageHeader.tsx`
- Modify: `TodosPage.tsx`, `HealthPage.tsx`, `SecurityPage.tsx`, `SettingsPage.tsx`, `LogsPage.tsx`
- Test: `tests/ui_page_headers.py`

- [ ] Browser test measures the header border against the main pane on `/tasks`, `/todos`, `/health`, `/security`, `/settings`, and `/logs`, and checks the tasks list still has `max-w-3xl`.
- [ ] Run and confirm FAIL for the inset pages.
- [ ] Move those titles into `PageHeader`. Leave existing content width classes.
- [ ] Run the test and confirm PASS.
- [ ] Commit.

### Task 2: Remaining titled pages

**Files:**
- Modify the pages already listed in `.agents/task/ui-consistency.md` that have a header but still wrap the title with content width.
- Test: `tests/ui_page_headers.py`

- [ ] Extend the measurement to briefing, calendar, bills, memory, knowledge, channels, and `/skills`.
- [ ] Adjust only headers that fail the edge measurement.
- [ ] Run the UI test at a narrow viewport and confirm PASS.
- [ ] Commit.
