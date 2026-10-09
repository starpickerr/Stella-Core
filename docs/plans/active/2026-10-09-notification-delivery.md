# Notification Routing and Delivery Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Let desktop UI and Agent configure the same explicit notification route for todo reminders and scheduled tasks, with durable delivery results and an optional user chosen backup.

**Architecture:** TodoService continues to own reminder lifecycle and SchedulerService continues to own independent tasks. A shared notification routing module validates destinations and dispatches through live channel instances. Todo reminder deliveries and scheduler job runs keep separate durable records but share status names and dispatch behavior; task execution output is cached before delivery.

**Tech Stack:** Python/SQLite, React/TypeScript, pytest, Playwright.

**Spec:** `.agents/task/DEVELOPMENT_PLAN.md` stage 2 and cross stage acceptance; `.agents/task/DEVELOPMENT_PROGRESS.md` records the verified starting point.

## Global Constraints

- Preserve old todo reminder and scheduler task data; absent route uses the existing desktop default.
- An explicit primary channel must never silently switch; backup is disabled by default and only used after explicit user selection.
- Weixin requires a live iLink session and `context_token`; never expose tokens to the client or claim final delivery from platform acceptance.
- Todo and scheduler mutations go through the same Application API from UI and Agent; no duplicate reminder task for a channel change.
- Tests use temporary `HOME`, `STELLA_DATA_DIR` and workspace; external sending uses fake channels unless an isolated test account is authorized.

## Review Focus

- A task requested “only Feishu” has no backup after later edits and never sends on Weixin.
- A Weixin session that expires between schedule creation and execution records an explicit failure without rerunning saved Agent output.
- A timeout with unknown platform result is not retried blindly, and a late reminder expires rather than piling up.
- Editing a todo reminder route updates its existing scheduler link instead of adding another task.
- `14:00+08:00` fires at the same instant as `06:00+00:00`, including after restart.

## Files and responsibilities

- `agent/scheduler/delivery.py`: existing destination catalog and normalization; grow into the shared route/dispatch entry for live channels.
- `agent/todos/service.py`, `agent/todos/scheduler_link.py`: persisted reminder route and idempotent lifecycle.
- `agent/scheduler/automation_store.py`, `agent/scheduler/integration.py`: separate execution and delivery state, retries and expiry for scheduled jobs.
- `application/api.py`: trusted todo/scheduler mutations exposed to desktop and Agent.
- `agent/tools/todos/todos_tool.py`, `agent/tools/scheduler/scheduler_tool.py`: Agent parameters and truthful results.
- `channel/desktop/desktop_channel.py`, `desktop/src/renderer/src/pages/TasksPage.tsx`, `desktop/src/renderer/src/pages/TodosPage.tsx`, `desktop/src/renderer/src/api/client.ts`, `desktop/src/renderer/src/types.ts`: API and local UI controls.

### Task 1: Shared route contract

**Interfaces:** `normalize_notification_route(route: dict | None, agent_id=None) -> dict` returns `{primary, backup_enabled, backup}`; `primary` and `backup` each use `normalize_destination`. Missing route represents the compatible desktop default; `backup_enabled` defaults to `False` and cannot be true without a valid backup. `destination_catalog()` reports configured, readiness and authorized recipient context without tokens.

- [ ] Add `tests/test_scheduler_delivery.py` cases for only Feishu, explicit backup, no recipient, stale Weixin token, unknown status and no token leak.
- [ ] Run focused tests RED; implement the route validator and status contract in `agent/scheduler/delivery.py`.
- [ ] Run focused tests GREEN and commit `feat: validate explicit notification routes`.

### Task 2: Todo reminder route lifecycle

**Interfaces:** `TodoService.create_todo/update_todo` accept `reminder_delivery` only with `remind_at`; `get_todo/list_todos` return the persisted route and delivery summary. `Application.port("todos")` continues to be the sole write entry. `sync_task` retains the deterministic `todo-reminder:<id>` task key and queues one occurrence per local instant.

- [ ] Add failing tests in `tests/test_todos.py` for create/query/update/remove, cancellation and time zone equivalence; include legacy database migration.
- [ ] Add route storage, validation, link propagation and safe migration in TodoService; keep desktop reminder behavior for old rows.
- [ ] Run todo and scheduler link suites GREEN; commit `feat: persist todo reminder routes`.

### Task 3: Agent and desktop configuration parity

**Interfaces:** `TodosTool` accepts and returns `reminder_delivery`; `SchedulerTool` adds `destinations`, `update`, and explicit route parameters while using the same trusted scheduler mutation service as desktop. Any failed validation returns a tool failure, never a success formatted as an error string.

- [ ] Add failing Agent/API tests for the seven stage 2 example requests at the tool boundary, including invalid recipient and no duplicate task.
- [ ] Implement the shared scheduler mutation entry, expose it through Application API, and route desktop handlers plus both Agent tools through it.
- [ ] Run focused tests GREEN; commit `feat: share notification configuration with Agent`.

### Task 4: Durable delivery outcome and recovery

**Interfaces:** Scheduler job output persists before any send; delivery records expose pending, sending, accepted, failed, waiting, unknown and expired, with attempt/recipient/platform response. Todo reminder deliveries use the same status vocabulary. Backup dispatch only follows the saved `backup_enabled` policy and explicit failure rules.

- [ ] Add failing store/dispatcher tests for successful acceptance, explicit Weixin expiry, transient failure, unknown response, backup disabled/enabled, process restart and expiry.
- [ ] Implement shared channel dispatch and bounded recovery, store delivery status separately from task execution, and wire todo reminder outbox plus scheduler job runs.
- [ ] Run relevant suites GREEN; commit `feat: persist notification delivery outcomes`.

### Task 5: UI and end to end acceptance

**Interfaces:** Task and todo editors show primary channel, recipient, optional backup, active status and test send; route updates use the same API as Agent. Known unavailable channels remain visible with a reason and refresh control.

- [ ] Add Playwright tests for task and todo editors, backup default off, only Feishu, Weixin no recipient, status refresh and test send.
- [ ] Implement local UI controls without changing the todo page below its top reminder editor.
- [ ] Run Playwright, TypeScript, incremental gate and isolated fake-channel integration scenarios; record external live sending as PASS only if actually performed.
- [ ] Review the diff, fix important findings with RED→GREEN tests, commit, and update `.agents/task/DEVELOPMENT_PROGRESS.md`.
