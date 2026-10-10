# Work Workspace Isolation Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Complete stage 5 of `.agents/task/DEVELOPMENT_PLAN.md`: private session and automation workspaces, project workspaces, explicit file sharing, and one authority for execution and file access.

**Architecture:** A new `agent.workspace.context` resolver owns Work paths and returns a context for an Agent/session/task. The runtime, Desktop file APIs, tool gateway, sandbox and previews consume that context rather than inferring scope from `cwd`. Existing project bindings stay in `project_store`; a missing bound project is an error. Shared files live in `work/shared/` with an access manifest and exact file grants. Legacy root files stay in place and can be copied into a chosen workspace without deleting the originals.

**Tech Stack:** Python 3.9, React 18, TypeScript, existing `SecurityGateway`, `ProcessSandbox`, `WorkspaceService`, pytest, Playwright.

**Spec:** `.agents/task/DEVELOPMENT_PLAN.md` stage 5 and section 1.2.

## Global Constraints

- Keep `scheduler/`, `runs/`, Apple mapping and notification delivery data in their current business stores.
- Create Work directories only for a file operation or when the user opens that workspace; browsing metadata alone must not create them.
- A `source` conversation supplies context, not access to its private files. `reuse` and `new` keep their transcript behavior; task files use the stable task ID.
- A project task uses the authorized project directory. A deleted project binding is an explicit error.
- A share grants one real file to named sessions with read or write permission and can be revoked. A directory or symlink cannot be shared as a file.
- Legacy files remain intact. No automatic move or deletion of user files.
- Full Access never grants another chat's private Work directory, an unshared file, or managed data.

## Review Focus

- Invalid agent/session/task IDs must not traverse out of `work/`.
- A project deleted after binding must not silently send a scheduled or interactive write into a personal directory.
- A task referencing a source chat must use its stable task folder for private files.
- Revoking a share must take effect for already running tools and pending approvals.
- Shell children and `file://` Browser access must obey the same private file boundary as direct read/write tools.

---

### Task 1: Canonical Work context and compatibility

**Files:** Create `agent/workspace/context.py`; modify `agent/workspace/project_store.py`, `common/state_dir.py`; test `tests/test_work_context.py`.

**Interfaces:** `resolve_context(session_id, agent_id=None, task_id=None, ensure=False) -> WorkContext` returns `root`, `kind` (`session`, `project`, `automation`, `legacy`), and `work_root`; `get_project_binding()` distinguishes no binding from a missing directory. IDs are validated before path construction. `list_legacy_files()` lists only old top-level Work files; `copy_legacy_file()` copies an explicitly selected file into the active root without removing the source.

- [x] Write tests for two private sessions, same project, stable task runs, invalid IDs, missing project and safe legacy copy; run RED.
- [x] Implement the resolver and compatibility APIs; run focused tests GREEN.
- [x] Commit the resolver and tests.

### Task 2: Runtime, automation and Desktop workspace resolution

**Files:** Modify `agent/protocol/agent.py`, `bridge/agent_bridge.py`, `agent/runtime/tool_invocation.py`, `agent/scheduler/conversation.py`, `agent/scheduler/integration.py`, `channel/desktop/desktop_channel.py`, `agent/workspace/service.py`; test `tests/test_work_runtime.py`, `tests/test_project_conversation_scope.py`, `tests/test_scheduler_conversation.py`.

**Interfaces:** Interactive Agent tools, prompt cwd, file tree/search/resolve/preview and Desktop Security Center report the same context root. Scheduled Agent runs use `automations/<agent>/<task>` unless an actual project is bound, regardless of `source/reuse/new`; task run IDs do not create a new file root. Missing projects fail before execution. The per-session runtime no longer retains a prior session's `cwd` after switching context.

- [x] Write failing tests for runtime/API consistency, stable automation root and missing project failure; run RED.
- [x] Integrate the resolver at the named boundaries; run focused tests GREEN.
- [x] Commit runtime integration and tests.

### Task 3: Exact file sharing and user controls

**Files:** Create `agent/workspace/shares.py`; modify `channel/desktop/desktop_channel.py`, `desktop/src/renderer/src/api/client.ts`, `desktop/src/renderer/src/components/FileTree.tsx`, `desktop/src/renderer/src/components/WorkspacePanel.tsx`; test `tests/test_work_shares.py`, `tests/ui_work_shares.py`.

**Interfaces:** Authenticated Desktop endpoints list, create and revoke shares. Creating a share copies a regular non-symlink file to `work/shared/<share_id>/<filename>` and records owner and named recipient sessions plus `read`/`write`. Recipient views show only granted files. Revocation removes the grant immediately but retains shared data for the owner; no API lists unrelated private files.

- [x] Write failing service/API/browser tests for exact file selection, read/write, revoke and symlink rejection; run RED.
- [x] Implement the manifest, API and compact file-panel controls; run focused tests GREEN.
- [x] Commit sharing and tests.

### Task 4: Private boundary across tools and processes

**Files:** Modify `agent/permission/gateway.py`, `agent/permission/process_sandbox.py`, `agent/runtime/tool_invocation.py`, `agent/tools/browser/browser_tool.py`; test `tests/test_work_boundaries.py`, `tests/test_process_sandbox.py`.

**Interfaces:** A centralized `WorkContext` predicate decides whether an absolute real path is own workspace, an exact granted shared file, another private workspace or managed Work metadata. Direct file tools, search/preview, Browser file navigation and Shell approvals use it. The OS sandbox hides other private folders and unrelated shares even in Full Access; if the platform cannot enforce this, Shell launch fails closed. Pending approvals bind to the current context and share grant version.

- [x] Write failing tests for cross-session read/write, path traversal, symlink escape, share revocation, Shell child process and Browser file access; run RED.
- [x] Enforce the same boundary in gateway and sandbox; run focused tests GREEN, including actual OS sandbox where available.
- [x] Commit boundary enforcement and tests.

### Task 5: Stage 5 integration and record

**Files:** Modify `.agents/task/DEVELOPMENT_PROGRESS.md`; run focused Work tests, browser checks and `.venv/bin/python scripts/quality_check.py incremental`.

- [x] Review the branch diff for missed path and identity boundaries; fix important findings with regressions.
- [x] Run the full incremental gate in temporary HOME and STELLA_DATA_DIR; record PASS/FAIL/SKIP, especially OS sandbox availability.
- [ ] Commit the progress record, then continue to stage 6.
