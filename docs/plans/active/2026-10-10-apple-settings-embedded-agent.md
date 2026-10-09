# Apple Settings and Embedded Agent Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Complete stage 4 of `.agents/task/DEVELOPMENT_PLAN.md`: one Apple connection center and persistent in-page Agent conversations for Calendar and Todos.

**Architecture:** Keep `Application.apple_calendar()` and `.apple_reminders()` as the only sync managers. Add persistent automatic-sync switches to those managers, then build one settings surface that drives the existing preview/confirmation APIs for each kind. Reuse `chatStore`, `ChatInput`, `MessageBubble`, session history, and the existing approval API inside a small shared embedded Agent component; page menus send preset requests into that component.

**Tech Stack:** Python 3.9, Swift EventKit helper already implemented, React 18, TypeScript, Zustand, Electron desktop HTTP API, pytest, Playwright.

**Spec:** `.agents/task/DEVELOPMENT_PLAN.md` stage 4 and section 1.2.

## Global Constraints

- Do not touch real Apple stores, credentials, or user data during tests; use fake bridges and mocked desktop HTTP.
- A one-time transfer requires exact source and item IDs, preview, and confirmation; it does not enable continuous sync.
- Calendar and Reminders authorization, lists, direction, automatic switch, mappings, conflicts, and diagnostics remain independent.
- Todo changes below the quick input and embedded Agent region are out of scope; preserve tree, focus, filters, sort, and details.
- Embedded runs keep their session and stream on collapse, navigation, and return. Calendar and Todos use different sessions and drafts.
- Use existing brand tokens and compact controls. Keep the Apple integration summary in settings; page menus are entry points.

## Review Focus

- A user starts a long Agent run and leaves the page: the same run and tool status reappear on return.
- A preset Apple request is sent exactly once, rather than merely copied into an input or duplicated by React remount.
- A user previews an Apple scope then changes its selection: the old confirmation cannot apply.
- A stale or revoked Apple permission disables data reads and writes without erasing prior mappings.
- Closing the embedded panel must not switch the global main-chat session or grant another page its private draft.

---

### Task 1: Persisted automatic sync and desktop connection contract

**Files:** Modify `agent/calendar/apple_sync.py`, `agent/todos/apple_sync.py`, `channel/desktop/desktop_channel.py`, `desktop/src/renderer/src/api/client.ts`, `desktop/src/renderer/src/types.ts`; test `tests/test_apple_calendar_api.py`, `tests/test_apple_reminder_api.py`, `tests/test_apple_reminder_sync.py`.

**Interfaces:** Both managers expose `auto_enabled` in `status()` and `set_auto(enabled: bool)`. A configured connection can run manually with auto off, and turning auto off stops its watcher promptly without disconnecting. Desktop provides independent `POST /api/calendar/apple/auto` and `/api/todos/apple/auto`; startup resumes only enabled, authorized watchers for both kinds. Connection, scope preview, inventory, exact-item preview/write, sync, resolution and disconnect APIs remain authoritative.

- [ ] Add failing isolated tests for switch persistence/restart, independent Calendar/Reminders toggles, and startup permission-safe behavior; run focused pytest RED.
- [ ] Implement setting, start/stop semantics, desktop endpoints and client contracts. Make configure respect the saved automatic switch; disconnect stops the watcher without deleting data.
- [ ] Run focused pytest GREEN; commit `feat: persist independent Apple automatic sync settings`.

### Task 2: Unified Apple settings surface

**Files:** Create `desktop/src/renderer/src/pages/settings/AppleIntegrations.tsx`; modify `desktop/src/renderer/src/pages/SettingsPage.tsx`, `desktop/src/renderer/src/pages/calendar/AppleCalendarPanel.tsx` usage, `desktop/src/renderer/src/api/client.ts`, `desktop/src/renderer/src/types.ts`; test `tests/ui_apple_settings.py` and existing `tests/ui_apple_calendar.py`.

**Interfaces:** Deep links `/settings?tab=integrations&section=apple-calendar` and `...apple-reminders` select the shared Apple settings tab. Each card shows authorization, sources, direction, automatic switch, last success, errors/conflicts, manual sync and disconnect. Continuous connection uses scope preview token; any selection/direction change invalidates it. One-time import/export lists exact Apple/Stella items (calendar inventory uses an explicit window), previews selected IDs, then confirms with the returned token. Existing Calendar modal is removed as a second settings source. Empty, permission-denied, loading and API-error states remain actionable.

- [ ] Write browser tests that initially fail for both deep links, independent switches, scope preview/confirmation, exact-item one-time transfer, stale preview failure and disconnect.
- [ ] Build the settings page with two calm, distinct sections using existing surfaces, typography, borders, and accent colors; no unrelated settings redesign.
- [ ] Run Playwright UI and TypeScript/ESLint GREEN; commit `feat: manage Apple connections in one settings center`.

### Task 3: Shared embedded Agent session component

**Files:** Create `desktop/src/renderer/src/components/EmbeddedAgent.tsx` and `ChatApprovalDialog.tsx` as needed; modify `desktop/src/renderer/src/components/ChatInput.tsx`, `desktop/src/renderer/src/store/draftStore.ts`, `desktop/src/renderer/src/store/sessionStore.ts`, `desktop/src/renderer/src/pages/ChatPage.tsx` if extracting approval UI; test `tests/ui_embedded_agents.py` and focused Node tests if state helpers need pure coverage.

**Interfaces:** `<EmbeddedAgent context="calendar" | "todos" presetRequest?: { id: string; text: string } onRunDone?>` owns a stable page-specific session ID, collapses by default, expands for interaction, consumes each preset `id` once, calls `chatStore.send()` directly, loads saved history, streams `MessageBubble` tool states, offers stop/new context and existing approval decisions. `ChatInput` accepts a per-context draft key, defaulting to the main-chat draft. No route navigation or global active-session change on send. Remount reloads history, while the store-owned EventSource continues and `onRunDone` refreshes the relevant business list when the page is mounted.

- [ ] Add failing browser tests for independent sessions/drafts, real `sendMessage` invocation, streaming status, collapse/return, history recovery, and approval action.
- [ ] Implement the shared component and any small extracted hooks with stable handlers and cleanup limited to UI subscriptions, never the active stream.
- [ ] Run browser tests, typecheck and ESLint GREEN; commit `feat: embed persistent Agent conversations in business pages`.

### Task 4: Calendar and Todo page entry points

**Files:** Modify `desktop/src/renderer/src/pages/CalendarPage.tsx`, `desktop/src/renderer/src/pages/TodosPage.tsx`; test `tests/ui_embedded_agents.py`, `tests/ui_apple_settings.py`, `tests/ui_apple_calendar.py`, `tests/ui_tasks.py`.

**Interfaces:** Calendar top shows EmbeddedAgent and an Apple menu with import preset, export preset, and settings deep link. Todo quick input region retains a visible direct-add action alongside Agent manage and Apple Reminders menu; Agent manage sends into its embedded session. Presets actually send, then refresh business rows after completion. Below the quick region, Todo tree and focus controls keep their DOM and behavior.

- [ ] Extend browser tests RED for exact menu labels, preset send-once, same-page conversation, settings navigation, Todo direct add, and unchanged tree/focus controls.
- [ ] Wire menus and in-page Agent, removing the old Todo redirect and old Calendar modal entry. Keep existing manual controls.
- [ ] Run all relevant browser checks, typecheck and ESLint GREEN; commit `feat: connect Calendar and Todos to embedded Agent and Apple settings`.

### Task 5: Stage 4 integration and record

**Files:** Modify `.agents/task/DEVELOPMENT_PROGRESS.md`; run `tests/ui_apple_settings.py`, `tests/ui_embedded_agents.py`, `tests/ui_apple_calendar.py`, `tests/ui_tasks.py` and `.venv/bin/python scripts/quality_check.py incremental`.

- [ ] Verify both pages and settings against isolated browser backend, then run the full incremental gate with the installed Playwright browser path.
- [ ] Perform the plan's final read-only branch review, fix important findings with RED→GREEN regressions, and mark real Apple/packaged/model-interaction tests SKIP if not run.
- [ ] Update progress with exact PASS/FAIL/SKIP evidence; commit `docs: record unified Apple settings and embedded Agent verification`.
