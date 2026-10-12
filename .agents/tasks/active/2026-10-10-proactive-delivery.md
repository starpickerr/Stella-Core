# Proactive Delivery Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Send one proactive message to one connected desktop, Telegram, or WeCom long-connection target, and stop using backup destinations.

**Architecture:** `agent/scheduler/delivery.py` owns the allowed channel set, catalog, and route normalization. `agent/scheduler/dispatch.py` sends only the primary leg and treats platform or OS confirmation as success. Desktop notifications use the existing Electron claim/ack loop; Telegram and WeCom websocket reuse their current send primitives and wait for the platform result.

**Tech Stack:** Python 3.9, existing scheduler and todo stores, Electron `Notification`, pytest, Playwright.

**Spec:** `.agents/tasks/active/security-center/requirements.md` sections 1–4.

## Global Constraints

- Selector options are only connected `desktop`, `telegram`, and `wecom_bot`; count is 0–3.
- One send uses one channel and one receiver. Failure does not try another channel or receiver.
- New requests that set `backup_enabled` true or a `backup` object are rejected.
- Stored backup fields are dropped on read and on the next save. Records themselves stay.
- An old primary outside the three channels is kept, marked `needs_reselect`, and is not sent. `web` is not converted into a desktop notification.
- Success requires Telegram `message_id`, WeCom `errcode == 0`, or a desktop ack with `shown` true.
- Tests use isolated data and never contact a real user or group.

## Review Focus

- A disconnected channel disappears from the catalog but a previously saved choice remains and the next send fails in place.
- WeCom webhook mode is not offered as the long-connection channel.
- A desktop client that is connected but has notifications disabled is visible and its send fails with the permission reason.
- Agent tool calls cannot attach a backup or choose an unlisted channel.
- Reading a task that still has backup JSON does not raise and does not deliver that backup.

---

### Task 1: Route contract

**Files:**
- Modify: `agent/scheduler/delivery.py`
- Modify: `agent/scheduler/dispatch.py`
- Modify: `agent/scheduler/mutations.py`
- Modify: `agent/tools/scheduler/scheduler_tool.py`
- Modify: `agent/tools/todos/todos_tool.py`
- Test: `tests/test_proactive_delivery.py`

**Interfaces:**
- Produces: `PROACTIVE = ("desktop", "telegram", "wecom_bot")`
- Produces: `normalize_notification_route(route, agent_id=None) -> {"primary": dict | None, "needs_reselect": bool}`
- Produces: `load_saved_route(route) ->` the same shape, stripping backup without error
- Produces: `destination_catalog(agent_id=None) -> list` of only connected proactive channels

- [ ] Write tests that reject backup payloads, strip old backup on load, mark `web`/`feishu`/`weixin` primaries `needs_reselect`, and show an empty catalog when nothing is connected.
- [ ] Run the new test and confirm FAIL.
- [ ] Implement the contract. `dispatch_notification` never reads `backup`. An unsupported primary returns `DeliveryOutcome("failed", "需要重新选择渠道")` without calling the channel.
- [ ] Update callers and existing tests that still submit backup or the old channel set.
- [ ] Run `tests/test_proactive_delivery.py tests/test_notification_dispatch.py tests/test_notification_routes.py tests/test_scheduler_delivery.py` and confirm PASS.
- [ ] Commit.

### Task 2: Three send paths

**Files:**
- Modify: `agent/scheduler/dispatch.py`
- Modify: `channel/telegram/telegram_channel.py`
- Modify: `channel/wecom_bot/wecom_bot_channel.py`
- Modify: `agent/todos/service.py`
- Modify: `channel/desktop/desktop_channel.py`
- Test: `tests/test_proactive_delivery.py`

**Interfaces:**
- Produces: `TelegramChannel.send_proactive(chat_id, text) -> {"message_id": str}`
- Produces: `WecomBotChannel.send_proactive(chat_id, text, is_group=False) -> {"errcode": int}` using `_send_and_wait` and `aibot_send_msg`
- Produces: desktop outbox claimed by `DesktopNotificationClaimHandler` and closed by `DesktopNotificationAckHandler`

- [ ] Test Telegram send with a known chat and no fresh inbound update; unknown chat fails before send.
- [ ] Test WeCom websocket confirmation; webhook mode and a missing chat fail before send.
- [ ] Test desktop enqueue stays unaccepted until ack `shown` is true; `shown` false records the error.
- [ ] Implement the three adapters. Catalog recipients come from chats already stored for that channel, not from the latest inbound message.
- [ ] Run the proactive tests and confirm PASS.
- [ ] Commit.

### Task 3: Editors

**Files:**
- Modify: `desktop/src/renderer/src/pages/TasksPage.tsx`
- Modify: `desktop/src/renderer/src/pages/TodosPage.tsx`
- Modify: `desktop/src/renderer/src/i18n.ts`
- Test: `tests/ui_notification_routes.py`

- [ ] Change the UI test so the editors have no backup control, list only connected proactive channels, and show the reconnect prompt outside the list.
- [ ] Run it and confirm FAIL.
- [ ] Remove backup state and fields. Show `needs_reselect` on old unsupported primaries. Do not submit backup keys.
- [ ] Run `python scripts/ui_check.py` for the notification script and confirm PASS.
- [ ] Commit.
