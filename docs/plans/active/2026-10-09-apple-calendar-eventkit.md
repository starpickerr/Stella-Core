# Apple Calendar EventKit Integration Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Connect selected macOS calendars to Stella schedules with safe, persistent two-way synchronization.

**Architecture:** A signed Swift command-line helper owns all EventKit calls and exchanges one JSON request/response with Python over stdin/stdout; a watch mode emits change notifications. A Python sync service owns calendar selection, mappings, conflict/deletion state and retries, and reads/writes Stella schedules only through `Application.port("calendar")`. The desktop route and React panel call this service; the existing Agent calendar tool sees the same schedules.

**Tech Stack:** Swift/EventKit, Python/SQLite, Electron/React/TypeScript, pytest, Playwright.

**Spec:** User request in this conversation, 2026-10-09 (sections I–IX).

## Global Constraints

- Preserve all existing data and uncommitted work; work on the dedicated branch from `develop`.
- Tests use temporary `HOME`, `STELLA_DATA_DIR`, and workspace; never touch a real Calendar account.
- Sync adapter must use Application API for Stella writes, never its business database directly.
- No automatic bulk deletion of Apple events, and an unreadable calendar is never interpreted as deletion.
- No additional third-party runtime dependency; unsupported platforms expose a status.
- Commit without extra authorship trailers; merge local `develop` after verification, no remote push.

## Review Focus

- A restored mapping whose EventKit eventIdentifier changed must find the item by calendar, external identifier, and occurrence before writing.
- A permission revocation during a scan must retain mappings and local events, and recover on the next authorized scan.
- A recurring occurrence moved by an exception must retain identity and not create a duplicate.
- A process crash between native create and mapping commit must recover from the Stella marker, not create a second Apple event.
- A locally deleted linked event must require explicit confirmation before any Apple Calendar deletion.

## Files

- `native/apple-calendar/CalendarBridge.swift`, `Info.plist`, `build.sh`: native EventKit adapter and build.
- `agent/calendar/apple_bridge.py`: platform and subprocess protocol boundary.
- `agent/calendar/apple_sync.py`: per-user config, mapping, reconciliation, conflicts, retry and watch lifecycle.
- `agent/calendar/service.py`, `application/api.py`: sourced schedule mutation via the shared business API.
- `channel/desktop/desktop_channel.py`: authenticated sync endpoints.
- `desktop/src/renderer/src/pages/calendar/AppleCalendarPanel.tsx`, `CalendarPage.tsx`, `api/client.ts`, `types.ts`: integration UI.
- `desktop/package.json`, `desktop/build/build-backend.sh`, launch script: Info.plist and helper packaging.
- `tests/test_apple_calendar_sync.py`, Swift helper tests, `tests/ui_apple_calendar.py`: behavior and UI.

### Task 1: Sourced schedules through Application API

**Interfaces:** Produces `CalendarService.upsert_external_event(provider: str, source_key: str, payload: dict, event_id: str | None = None) -> dict`; made available on `Application.port("calendar")`. `provider` accepts only `apple_calendar` for this release. Existing `create_event`, `update_event`, `delete_event`, `list_events` remain compatible.

- [ ] Write pytest cases for source deduplication, remote update, imported provenance, local edit preservation, and validation rejection.
- [ ] Run them and observe expected failures.
- [ ] Add the minimal sourced upsert and API port method.
- [ ] Run focused calendar tests; expected PASS.
- [ ] Commit `feat: add sourced calendar event API`.

### Task 2: Native EventKit boundary

**Interfaces:** Produces `AppleCalendarBridge.call(op, **payload) -> dict` and `watch(on_change)`, where operations are `status`, `request_access`, `calendars`, `events`, `upsert`, `delete`. Native JSON events include `calendar_id`, `event_id`, `external_id`, `occurrence_date`, `stella_id`, content, all-day, timezone, recurrence metadata and last-modified. Each scan reports independently successful calendar IDs.

- [ ] Write Python protocol tests for unsupported platform, missing helper, malformed output, timeout, and safe command invocation; run RED.
- [ ] Implement subprocess adapter and Swift helper with macOS 14+ full-access API, EventKit CRUD, recurring occurrence lookup, JSON errors and `EKEventStoreChanged` watch.
- [ ] Build helper with a Calendar usage-description Info.plist and ad-hoc signing; run protocol tests GREEN and native compile/status smoke without requesting access.
- [ ] Commit `feat: add EventKit native bridge`.

### Task 3: Persistent reconciliation

**Interfaces:** Produces `AppleCalendarSync.status()`, `configure(calendars, direction)`, `sync(manual=False, confirm_deletions=False)`, `disconnect()`, `request_access()`, and `start_auto()`. State is a per-user SQLite database adjacent to `calendar.db`. Directions are `import`, `export`, `bidirectional`. Window is one year back and two years forward, with exclusive end.

- [ ] Write fake-bridge integration tests against a real temporary `Application` calendar port: first import, multiple calendars, idempotent rerun, local creation/export, remote update/delete, local update/delete confirmation, direction filters, conflict, recurrence exception, all-day/timezone, restart, permission revocation/unavailable calendar, crash-after-create recovery and failure retry. Run RED.
- [ ] Implement snapshot hashing, persistent mapping/selection/last-sync/conflicts, stable identity fallback, per-calendar scan success gate, explicit Apple deletion queue, and watcher/poll scheduling; run focused tests GREEN.
- [ ] Run full calendar tests and commit `feat: reconcile Apple and Stella calendars`.

### Task 4: Desktop integration and delivery

**Interfaces:** Authenticated routes `/api/calendar/apple/status`, `/access`, `/configure`, `/sync`, `/disconnect`; React panel uses these via `apiClient`. Existing Agent tool uses the same port and needs no second sync logic.

- [ ] Write route and browser interaction tests for unsupported/denied/connected states, calendar selection, direction, manual sync, conflicts, disconnect warning and deletion confirmation. Run RED.
- [ ] Add handlers, client types, panel, auto startup wiring, helper build/package integration and documentation; run focused tests GREEN.
- [ ] Run Swift build and status smoke, TypeScript check, Playwright, targeted pytest and `.venv/bin/python scripts/quality_check.py incremental` with isolated data; record PASS/FAIL/SKIP.
- [ ] Inspect diff, get fresh whole-branch review, fix important findings with RED→GREEN tests, commit, and merge local `develop` after green gates.
