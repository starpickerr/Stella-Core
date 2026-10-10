# Security Permission Modes Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Complete stage 6 of `.agents/task/DEVELOPMENT_PLAN.md`: first-class Read Only, Workspace Write, Full Access and Custom modes that actually bind tools, sandbox and approvals, without widening historical configs.

**Architecture:** Keep `SecurityGateway`, `SecurityPolicy` and `ProcessSandbox` as the three authorities. Persist four product presets in `security_policy`; migrate stored `approval`/`project-full`/`strict`/`standard` without privilege elevation. Work private paths, managed state, Apple system authorization and user-chosen notification channels stay independent of Full Access.

**Tech Stack:** Python 3.9, existing Security Center React page, pytest, Playwright.

**Spec:** `.agents/task/DEVELOPMENT_PLAN.md` stage 6, section 1.2 item 4, decision A7; `docs/security-permission-modes.md` operational limits.

## Global Constraints

- Do not bypass OS identity, Apple EventKit grants, other chats' private Work, unshared files, or managed Stella data even in Full Access.
- Historical `approval`, `project-full`, `full-access`, `custom`, `read-only` and `workspace-write` stores must not silently gain privilege or lose user rules.
- Stored `approval` becomes a Custom snapshot of its confirm-on-write rules; it must not become Read Only (deny) or Workspace Write (allow).
- Stored `project-full` is the same privilege as Workspace Write (workspace allow, outside confirm).
- `legacy_policy("workspace-write")` keeps the old `standard` snapshot (outside deny) so old `agent_permission_mode` users are not widened.
- Notification backup channels and Apple authorization remain separate from file/shell rules.
- Fail closed on damaged policy stores.

## Review Focus

- A session or project Custom deny must still apply after a global Full Access change that did not explicitly override that rule.
- Extra authorized roots must not include another session's private Work path.
- MCP tools with the same public name on two servers must not share one connection grant.
- Changing mode while a confirmation waits must re-check the latest policy and identity binding.
- Sandbox unavailable on the current OS must fail Shell closed, not claim isolation in the UI.

---

### Task 1: Product presets and conservative migration

**Files:** Modify `agent/permission/security_policy.py`, `desktop/src/renderer/src/api/client.ts`, `desktop/src/renderer/src/types.ts`, `desktop/src/renderer/src/pages/securityLocale.ts`; test `tests/test_security_center.py`.

**Interfaces:** `PRESETS` ids are `read-only`, `workspace-write`, `full-access`, `custom`. `default_policy()["preset"] == "workspace-write"`. `MODE_DEFINITIONS` names: 只读 / 工作区写入 / 完全访问 / 自定义. `validate_patch` accepts historical ids and rewrites them: `approval` → custom snapshot of old approval rules; `project-full` → `workspace-write`; `strict`/`standard` remain custom snapshots. `legacy_policy("read-only")` still denies workspace writes.

- [ ] Change `test_four_modes_and_legacy_snapshots_are_stable` so product ids are the four names above, `approval` migrates to custom without allowing workspace writes, `project-full` equals workspace-write; run RED.
- [ ] Implement preset table, aliases and copy; run focused tests GREEN.
- [ ] Commit presets and tests.

### Task 2: Runtime uses one effective policy

**Files:** Modify `agent/permission/security_policy.py`, `agent/runtime/tool_invocation.py`, `agent/permission/center.py`; test `tests/test_security_center.py`, `tests/test_security_gateway.py`.

**Interfaces:** `resolve()` documents that the `mode` argument is unused when a persisted `security_policy` exists; callers pass it only for `legacy_policy` fallback when no store is present. Interactive and scheduled checks use `resolve(...)` then `SecurityGateway.check(..., policy=policy)`. Read Only denies workspace writes; Workspace Write allows current Work/project writes and requires authorization outside; Full Access still denies other private Work, managed paths and credentials.

- [ ] Write failing tests for unused-mode-does-not-widen, Read Only write deny, Full Access private Work deny via resolved policy; run RED.
- [ ] Wire fallback only when the store is absent; run GREEN.
- [ ] Commit runtime policy resolution.

### Task 3: Security Center shows sandbox, approval and tool rules separately

**Files:** Modify `agent/permission/center.py`, `desktop/src/renderer/src/pages/SecurityPage.tsx`, `desktop/src/renderer/src/pages/securityLocale.ts`; test `tests/test_security_center.py`, `tests/ui_security_modes.py`.

**Interfaces:** Overview reports `process_isolation` without rewriting Full Access to hide an enabled sandbox. Full Access copy states private Work, managed data, Apple grants and credentials remain blocked. Permissions tab lists four product modes, Custom copy/restore, current workspace root and sandbox status. Browser: select Read Only, confirm Full Access warning, see isolation still enabled.

- [ ] Write failing API and Playwright tests for mode labels, Full Access warning text and sandbox status; run RED.
- [ ] Update Center payload and page copy; run GREEN.
- [ ] Commit Security Center alignment.

### Task 4: Custom extras stay scoped

**Files:** Modify `agent/permission/security_policy.py`, `agent/permission/gateway.py` if extra_roots can name private Work; test `tests/test_security_center.py`, `tests/test_work_boundaries.py`.

**Interfaces:** Custom may set extra_roots, connection grants, MCP/Browser/Git/Skill rules, Allow/Confirm/Deny. `extra_roots` that resolve inside another private Work directory or `work/shared` parent are rejected. Copy-from-current and restore-default keep existing PolicyEditor behavior. Apple/notification settings are not stored in `security_policy`.

- [ ] Write failing tests rejecting foreign Work extra_roots and preserving Custom copy/restore; run RED.
- [ ] Enforce the extra_roots predicate; run GREEN.
- [ ] Commit Custom scoping.

### Task 5: Stage 6 record

**Files:** Modify `.agents/task/DEVELOPMENT_PROGRESS.md`, `.agents/task/DEVELOPMENT_PLAN.md`, `docs/security-permission-modes.md`.

- [ ] Run `.venv/bin/python scripts/quality_check.py incremental` and record PASS/FAIL/SKIP including OS sandbox.
- [ ] Update progress, archive completed plans under `docs/plans/completed/` when this and the Work plan reviews are clean.
- [ ] Commit the record.
