# Apple Reminders and Agent Integration Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Complete stage 3 of `.agents/task/DEVELOPMENT_PLAN.md`: a shared EventKit boundary, independent Apple Reminders sync, and Apple Calendar/Reminders operations available to Agent through the same services used by desktop.

**Architecture:** Extend the existing Swift helper and Python process bridge with reminder operations and separate EventKit authorization. Keep Calendar and Reminders mappings, models, and conflict records independent. Write Stella changes through Application ports and the existing CalendarService/TodoService; background reconciliation is deterministic and never invokes an LLM.

**Tech Stack:** Swift EventKit, Python 3.9, SQLite, Electron desktop HTTP API, pytest, native Swift tests.

**Spec:** `.agents/task/DEVELOPMENT_PLAN.md` stages 3A–3D and the product constraints in section 1.2.

## Global Constraints

- Calendar and Reminders permissions are independent; never read Apple data before the corresponding full access grant.
- Preserve Stella todo hierarchy, dependencies, advanced status, focus/progress, reminder route, and unrelated fields when importing a reminder.
- `cancelled` is never translated to Apple `completed`; Apple incomplete must not erase Stella `in_progress`, `waiting`, or `blocked`.
- A missing list, revoked permission, failed scan, empty inventory, or changed EventKit identifier must not cause bulk local deletion.
- First sync, bulk writes, and deletion need a preview/explicit confirmation boundary; a one-time operation does not enable ongoing sync.
- Test against temporary `HOME`, `STELLA_DATA_DIR`, a fake EventKit adapter and test calendars/lists. Live Apple and packaged behavior remain SKIP unless actually tested in isolated targets.

## Review Focus

- An imported reminder moves between Apple lists while its `calendarItemIdentifier` changes: one Stella todo remains linked; no duplicate or deletion.
- An imported reminder is marked incomplete in Apple after Stella moved to `waiting`: the Stella status stays `waiting`.
- A list returns an empty inventory while previously containing mapped reminders: no local delete without later positive evidence and confirmation.
- A reminder's due date has a floating local time or a zone offset: Stella displays the same intended wall time.
- Auto sync restarts after a failed helper call: saved mappings and pending conflicts are reused without duplicate writes.

---

### Task 1: Shared EventKit reminder operations and permissions

**Files:** Modify `native/apple-calendar/CalendarBridge.swift`, `native/apple-calendar/Info.plist`, `desktop/package.json`, `agent/calendar/apple_bridge.py`; test `tests/test_apple_bridge.py`, `native/apple-calendar/tests/main.swift` or a focused Swift helper test.

**Interfaces:** Add operations `reminder_status`, `reminder_request_access`, `reminder_lists`, `reminders`, `reminder_lookup`, `reminder_upsert`, `reminder_delete`, and `reminder_watch` to `AppleCalendarBridge.call`/`watch`, retaining all calendar operations. Reminder rows carry `list_id`, `reminder_id`, `external_id`, `stella_id`, title, notes, due/planned/remind values with timezone, priority, completion, recurrence, and `last_modified`; scan returns successful and failed list IDs.

- [ ] Add failing fake-helper tests for allowed reminder operations, independent authorization, unsupported platform, invalid response, timeout and watch events. Add a native Swift test for reminder date/status conversion that uses no real Reminder store.
- [ ] Run focused tests RED; note the actual failure.
- [ ] Extend the existing helper and bridge, with `NSRemindersFullAccessUsageDescription` in both packaging and helper plist. Guard every reminder read/write with reminder authorization; use `requestFullAccessToReminders` on macOS 14+ and the compatible older API elsewhere. Do not modify calendar auth behavior.
- [ ] Run Swift compile/test and focused Python tests GREEN; commit `feat: add independent EventKit reminder operations`.

### Task 2: TodoService external reminder boundary

**Files:** Modify `agent/todos/service.py`, `application/api.py`; test `tests/test_todos.py`, `tests/test_apple_reminder_todos.py`.

**Interfaces:** Add `TodoService.upsert_external_todo(source_key, payload, *, todo_id=None, reconciled=False)` to create/update Apple sourced todos through validated fields; add a sourced deletion method that requires an exact source key and explicit confirmation. Expose both via Application's todos port. Return standard decorated Todo rows.

- [ ] Write failing tests for import idempotency, Apple completion/incompletion, source identity, timezone/due/planned/remind conversion, scheduler link, and preservation of hierarchy, dependency, advanced status, custom reminder route, and user changes. Check `cancelled` never becomes Apple completed.
- [ ] Run focused tests RED.
- [ ] Implement the narrow source mutation boundary using existing TodoService validation and scheduler linkage. Keep unsupported fields untouched, avoid treating an Apple sync write as user modification, and ensure user deletion produces a tombstone that prevents silent reimport.
- [ ] Run focused tests GREEN; commit `feat: reconcile Apple reminders through TodoService`.

### Task 3: Independent Apple Reminders reconciliation

**Files:** Create `agent/todos/apple_sync.py`; modify the shared EventKit runtime as needed in `agent/calendar/apple_bridge.py`/`agent/calendar/apple_sync.py`; test `tests/test_apple_reminder_sync.py`.

**Interfaces:** `AppleReminderSync(bridge=None, db_path=None, todo_port=None, clock=None)` provides `status`, `request_access`, `configure(list_ids, direction)`, `preview(...)`, `sync(manual=False, confirm_deletions=False, confirm_local_deletions=False)`, `resolve_conflict(todo_id, choice)`, `disconnect`, `start_auto` and `stop_auto`. Use a separate SQLite map and settings store from Calendar. `direction` is import/export/bidirectional.

- [ ] Write failing fake-bridge tests for list selection, import/export, stable identity, idempotency, conflict, completion semantics, recurrence, restart, partial/empty scans, list moves and deletion confirmation. Include every Review Focus case owned by sync.
- [ ] Run focused tests RED.
- [ ] Implement durable mapping/baselines, compare only Apple compatible fields, scan each selected list separately, and stage deletions for explicit confirmation. A missing or empty list is partial, never deletion evidence. Export only to a selected writable list. Keep retry and change notification scheduling in the existing EventKit runtime rather than introducing another transport.
- [ ] Run focused tests GREEN; commit `feat: sync Apple Reminders and Stella todos`.

### Task 4: Common Application API, desktop endpoints, and Agent tool

**Files:** Modify `application/api.py`, `channel/desktop/desktop_channel.py`, `agent/tools/calendar/calendar_tool.py`, `agent/tools/todos/todos_tool.py` or create one focused Apple integration tool and register it through the existing tool registry; test `tests/test_apple_calendar_api.py`, `tests/test_apple_reminder_api.py`, `tests/test_apple_agent_tool.py`.

**Interfaces:** `Application.apple_calendar()` and `Application.apple_reminders()` return the shared sync managers used by desktop and Agent. Agent operations expose permission/status, source lists, event/reminder lookup, selected-scope preview, configure, manual one-time import/export, sync, conflict resolution and disconnect. Desktop endpoints use those exact manager methods. All writes require existing tool/desktop authorization and explicit target IDs; no text-only success response.

- [ ] Add failing tests showing Agent and desktop read/write the same isolated manager and mappings; unknown source/target requires an error, no fabricated ID; one-time import/export leaves auto sync disabled.
- [ ] Run focused tests RED.
- [ ] Implement application manager accessors, desktop endpoints and Agent operations using the same calls. Keep Calendar and Reminders permissions and selected scopes separate.
- [ ] Run focused tests GREEN; commit `feat: expose Apple sync to desktop and Agent`.

### Task 5: Stage 3 integration and documentation

**Files:** Modify `.agents/task/DEVELOPMENT_PROGRESS.md`; test `tests/test_apple_calendar_sync.py`, `tests/test_apple_reminder_sync.py`, `tests/test_apple_agent_tool.py`, `tests/ui_apple_calendar.py`.

**Interfaces:** No new public contract; verify the four tasks together.

- [ ] Run focused fake EventKit integration tests for distinct Calendar/Reminders permission and data stores, restart, conflict and deletion protection; compile the Swift helper and check the packaged helper path.
- [ ] Run `.venv/bin/python scripts/quality_check.py incremental` and relevant browser UI; record PASS/FAIL/SKIP with real Apple authorization and packaged testing marked SKIP unless actually run.
- [ ] Review the whole diff for data loss or authorization bypass, fix important findings RED→GREEN, update progress, and commit `docs: record Apple Reminders integration results`.
