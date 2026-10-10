# Security Modes Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Make Full Access immediate and place all custom rule editing on the Security page.

**Architecture:** The policy preset in `security_policy.py` is the single enforcement source. The composer selector only selects a mode; the Security page owns detailed custom rules. Both frontends save through the existing policy APIs, with gateway hard boundaries unchanged.

**Tech Stack:** Python policy gateway, React/TypeScript, pytest, Playwright.

**Spec:** [Stella current requirements](../../../.agents/task/requirements.md#3-会话安全模式).

## Global Constraints

- Full Access changes the `high_risk` preset decision to `allow` only; hard private-workspace, managed-data, credential, account and Apple grants remain enforced.
- Preserve existing saved custom rules when switching to custom; do not replace them with an empty draft.
- No separate Full Access confirmation in composer or Security page.

## Review Focus

- Full Access allows a high-risk action that otherwise only required confirmation.
- A path into another session's private Work folder remains denied under Full Access.
- A credential or managed-data hard refusal remains denied.
- Switching to custom in composer retains prior rule overrides.
- Security page edits and persists an individual custom rule; composer exposes no rule editor.

---

### Task 1: Align policy and hard-boundary tests

**Files:** Modify `agent/permission/security_policy.py`; test `tests/test_security_gateway.py`, `tests/test_security_center.py`.

**Interfaces:** `rule(resolve(...), "high_risk") == "allow"` for a selected Full Access preset. `SecurityGateway.check(...)` still applies resource-specific hard denials.

- [ ] Write failing tests for Full Access high-risk allowance and for existing hard boundaries under that preset; run targeted tests to observe the allowance failure.
- [ ] Change `_FULL_ACCESS["high_risk"]` to `"allow"` without changing hard-denial code.
- [ ] Run targeted gateway and center tests; confirm PASS. Commit this logical change.

### Task 2: Simplify the two UI entry points

**Files:** Modify `desktop/src/renderer/src/components/PermissionSelector.tsx`, `desktop/src/renderer/src/pages/SecurityPage.tsx`, `desktop/src/renderer/src/pages/securityLocale.ts` where copy changes; test `tests/ui_security_modes.py` and any focused UI test.

**Interfaces:** Selecting `full-access` calls existing save once. Selecting `custom` in composer saves/activates a custom policy using current rules; detailed editing remains in `SecurityPage`.

- [ ] Update the isolated browser test to select Full Access once in each entry and assert the policy save and applied state; assert composer custom has no rule grid, while Security page does.
- [ ] Run the browser test and confirm its current failure.
- [ ] Remove `pendingFull` UI in both entry points and the composer rule editor; make composer custom selection preserve the current custom rule snapshot. Keep Security page `PolicyEditor` as the editing location.
- [ ] Run browser interaction and TypeScript checks; confirm PASS. Commit this logical change.

### Final gate

- [ ] Run `.venv/bin/python scripts/quality_check.py incremental` and isolated browser interaction; report PASS/FAIL/SKIP.
- [ ] Compare observed gateway decisions with the linked spec, inspect the diff, and record final commit(s).

## Progress

- Status: implemented on `fix/briefing-generation-20261010`. Full Access preset `high_risk` is `allow`. Composer and Security page apply Full Access in one click. Custom rule editing stays on the Security page; the composer only switches to custom using the current rules.
- Ruling: approval-resume and gateway confirmation fixtures now use `workspace-write`, because those tests cover the approval protocol and Full Access no longer confirms ordinary high-risk actions.
- Verification:
  - PASS `.venv/bin/python scripts/run_isolated.py .venv/bin/python -m pytest tests/test_security_center.py tests/test_security_gateway.py tests/test_security_approval_resume.py tests/test_work_boundaries.py -q` — 46 passed.
  - PASS `python scripts/ui_check.py` — Security modes UI: immediate Full Access and on-page custom editor passed. The same run also passed the other isolated UI scripts.
  - PASS `npx tsc --noEmit -p desktop/tsconfig.json`.
  - SKIP composer browser click: the isolated page opens `/#/security`, not a live chat composer. The composer component no longer renders a second confirm or a rule grid.
