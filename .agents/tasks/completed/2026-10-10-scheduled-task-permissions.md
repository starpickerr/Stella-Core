# Scheduled Task Permissions Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Let a user choose a scheduled task's unattended execution permission, reject approval-dependent work promptly, and report the task's actual business outcome.

**Architecture:** Persist an optional task-level permission mode. The authenticated desktop task editor can set it; Agent scheduler tools cannot. At run time, apply that mode through the existing permission policy and gateway for the duration of this task, with hard resource and account boundaries intact. Carry structured execution failure to the scheduler record instead of inferring success from a returned message.

**Tech Stack:** Python scheduler/permission services, task JSON store, React/TypeScript, pytest, Playwright.

**Spec:** [Stella current requirements](../active/security-center/requirements.md#4-定时任务运行权限).

## Global Constraints

- An absent mode on old tasks means inherit the bound conversation's existing behavior. The new-task default is also inherit. Do not migrate old tasks to a stronger mode.
- The four choices are inherit, read-only, workspace-write, and full-access. Store a stable internal value and display a localized label. A task-level choice affects execution policy only; it does not switch its conversation or grant a new workspace, account, connection, credential, or Apple system permission.
- Only a trusted user action can set or raise explicit task permission. Do not add a writable permission argument to `agent/tools/scheduler/scheduler_tool.py`. Validate allowed values and update provenance at the shared mutation boundary so direct or forged Agent-origin calls cannot escalate.
- Apply the task mode to both scheduled Agent tasks and direct scheduled tool calls. A permission decision that would require interactive approval must fail promptly in unattended execution, regardless of the presence of a cancellation event.
- Use temporary `HOME`, `STELLA_DATA_DIR`, task store, workspace, and mock tool/model responses in tests. Do not use real accounts or relax a hard boundary.

## Review Focus

- An old task without this field and a new default task both inherit. A saved explicit choice is used by Run Now and the next timer run.
- An Agent-created task or forged update cannot set full-access, including through a lower-level mutation API.
- Full-access at task level still denies another session's private workspace, managed data, credentials, missing connection scope, and Apple system grants.
- A would-confirm tool invocation returns a permission failure promptly, with no 3600-second `wait_for_decision` path.
- A failed or timed-out `briefing` action leaves the previous briefing intact and records task failure even if the Agent sends explanatory text.

---

### Task 1: Persist and protect the task permission choice

**Files:** Modify `agent/scheduler/mutations.py`, `agent/scheduler/store.py` if normalization is needed, `channel/desktop/desktop_channel.py`, `desktop/src/renderer/src/types.ts`, `desktop/src/renderer/src/api/client.ts` if type/API changes are needed; test `tests/test_scheduler_web_update.py`, `tests/test_scheduler_conversation.py` and a focused Agent-tool test.

**Interfaces:** A task record may contain `run_permission_mode` with `read-only`, `workspace-write`, or `full-access`; absent or `inherit` means the old inherited behavior. Desktop create/update accepts a validated choice from the authenticated user route. Shared mutation code knows the caller provenance and refuses Agent-origin explicit elevation.

- [ ] Write failing tests for creation, edit, persistence/reload, old-task inheritance, invalid values, and Agent-origin elevation attempts at both web and shared mutation layers.
- [ ] Run the focused tests through `scripts/run_isolated.py`; confirm they fail for the expected missing behavior.
- [ ] Add the optional field and validation while preserving all existing task fields, scheduling, conversation binding, and notification settings. Keep the Agent scheduler tool schema unable to set the field.
- [ ] Run focused tests; confirm PASS. Commit this logical change.

### Task 2: Apply the selected policy during unattended execution

**Files:** Modify `agent/scheduler/integration.py`, `agent/runtime/tool_invocation.py` or the central policy context boundary, and `agent/permission/security_policy.py` only if required to reuse existing presets; test `tests/test_scheduler_conversation.py`, `tests/test_security_approval_resume.py`, `tests/test_briefing_scheduler.py`.

**Interfaces:** Each scheduled run resolves its effective permission once, scoped to that run, and restores the prior context afterward. Both `_execute_agent_task` and `_run_scheduled_tool` use the effective mode. The same gateway enforces resource-specific hard denials. Scheduled invocations are explicitly noninteractive so `confirm` produces a permission error, never an approval wait.

- [ ] Add tests with an inherited task, each explicit mode, Run Now and timer execution; prove the mode does not leak to later conversation or task calls. Add a short-timeout test that would fail if approval waits.
- [ ] Run focused tests and confirm failures on current behavior.
- [ ] Apply the task-scoped mode at the existing trusted permission boundary; route scheduled tool invocations through a noninteractive decision. Do not bypass the gateway or rewrite connection grants.
- [ ] Run focused scheduler/security tests; confirm PASS. Commit this logical change.

### Task 3: Record the actual task outcome

**Files:** Modify `agent/scheduler/integration.py`, `agent/scheduler/outcome.py` or the existing structured reply boundary as needed; test `tests/test_briefing_scheduler.py`, `tests/test_scheduler_run_now.py`.

**Interfaces:** A tool or Agent task propagates structured permission, timeout, cancellation, and business-action failure into `ExecutionOutcome`. The run record uses that status, not the fact that a text reply or notification was delivered. A successful briefing requires successful generation and persistence.

- [ ] Add failing tests for permission refusal, timeout, tool error, and briefing not produced while the Agent returns explanatory text; assert task history is failed with a useful reason and no saved-briefing replacement.
- [ ] Run focused tests; confirm intended failures.
- [ ] Propagate execution status from the tool/Agent bridge to scheduler history. Keep notification delivery separate from business success, and avoid parsing free-form reply text for failure.
- [ ] Run focused scheduler tests; confirm PASS. Commit this logical change.

### Task 4: Expose the choice and result in the task UI

**Files:** Modify `desktop/src/renderer/src/pages/TasksPage.tsx`, `desktop/src/renderer/src/types.ts`, and local task copy; test `tests/ui_tasks.py` or a focused isolated browser scenario.

**Interfaces:** The task editor has a labeled “运行权限” button/selector with the four choices, defaulting to “沿用绑定对话”. The list/detail shows the saved choice and any failed run's reason. Saving/reopening and Run Now use the persisted value.

- [ ] Write a failing browser interaction for choosing each mode, saving, reopening, viewing the task, and using Run Now; include an old task with no field and a visible permission failure.
- [ ] Run the browser scenario and confirm its current failure.
- [ ] Add the selector and display using the existing task form and API; keep notification channel and bound conversation controls independent.
- [ ] Run browser interaction and TypeScript checks; confirm PASS. Commit this logical change.

### Final gate

- [ ] Run `.venv/bin/python scripts/quality_check.py incremental` and the affected isolated browser interaction; record PASS/FAIL/SKIP with the actual commands and any concrete limitation.
- [ ] Compare the behavior with every requirement in the linked spec, inspect the diff and commit(s), and leave `develop` untouched unless the user explicitly asks to merge.

## Progress

- Status: implemented on `fix/briefing-generation-20261010`.
- Commits: `a01e8628` persist user-chosen mode, `73f79d3e` apply it without an approval wait, `7369fdcc` structured tool failure, `2a1dc20a` editor and list.
- The one-hour wait matches `agent_stream._permission_denial`: a scheduled run registers a cancel event, and that used to set `wait_for_approval`. Scheduled runs now pass `noninteractive=True`.
- Verification:
  - PASS isolated pytest `tests/test_scheduler_web_update.py tests/test_scheduler_conversation.py` — 23 passed.
  - PASS isolated pytest `tests/test_scheduler_delivery.py tests/test_security_approval_resume.py` — 29 passed.
  - PASS isolated pytest `tests/test_briefing_scheduler.py` — 8 passed.
  - PASS `tests/ui_tasks.py` through the isolated renderer: task editor saves 完全访问, reopens it, runs now, and shows a failed reason. `npx tsc --noEmit -p desktop/tsconfig.json` passed.
  - PASS `.venv/bin/python scripts/quality_check.py incremental` — ruff, pytest (1509 passed, 4 skipped), eslint, build, typecheck, node, and ui. SKIP policy: no relevant changes. Isolated `tests/ui_tasks.py` passed inside that ui step.
