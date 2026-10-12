# Stella Full Audit — 2026-10-08

## Scope and isolation

- Branch: `codex/stella-quality-audit-20261007`; baseline: `f4131e7c` (`develop`). The audit did not change business code or user data.
- Stack reviewed: Python Agent and HTTP backend, Electron main process, React/TypeScript renderer, SQLite stores. This was not a production deployment audit.
- `.venv/bin/python scripts/quality_check.py full` ran checks with temporary `HOME`, `STELLA_DATA_DIR`, cache and workspace state. The browser test used local Vite and mocked backend responses. No live external account or real user database was supplied.
- Overall automated result: **FAIL**, because full-repository Ruff returned 492 findings. Passing tests do not clear that failure.

## Automated evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Ruff (`E4,E7,E9,F`) | **FAIL** | 492 findings; 152 automatically fixable according to Ruff. Run `.venv/bin/ruff check --select E4,E7,E9,F agent application bridge channel cli common models scripts tests translate voice app.py config.py`. |
| Python tests | **PASS with skips** | `1265 passed, 4 skipped, 1 warning` from `.venv/bin/python -m pytest tests -q` in the isolated runner. |
| Desktop typecheck | **PASS** | `npm --prefix desktop run typecheck` completed renderer and main `tsc --noEmit` checks. |
| Node tests | **PASS** | `node --experimental-strip-types --test tests/todoFocus.test.mjs` exited 0. |
| Playwright interaction | **PASS, narrow coverage** | `tests/ui_smoke.py` checked login form disabled state, input, rejected password feedback and continued visibility. It ran against local Vite with mocked health and auth endpoints. |

The four pytest skips are three Windows integration cases in `tests/test_bash_streaming.py` (this run was on macOS) and one `tomllib` case in `tests/test_syntax_gate.py` (this venv is Python 3.9). The warning is urllib3's `NotOpenSSLWarning` for this interpreter's LibreSSL 2.8.3. Two image tests initially skipped because Pillow was absent; after installing the already declared runtime dependency into Stella's `.venv`, the final run included them.

## Domain review

| Domain | Assessment and evidence |
| --- | --- |
| Code quality and possible bugs | **Issue confirmed.** Ruff has 492 findings, including seven `F821` undefined exception references in model adapters. Focused offline reproduction confirmed one runtime failure below. |
| Architecture and dependencies | **Partially reviewed.** `application/api.py` routes user-scoped calendar, todos, bills and briefing operations; `agent/runtime/tool_invocation.py` owns the tool permission gate; Electron `desktop/src/main/index.ts` hosts a React renderer. Typechecking passed. Dependency cycles and clean installs across platforms were not checked. |
| Backend and frontend functionality | **Partially verified.** Full pytest and TypeScript checks passed; the UI test covered login rejection. Other screens and successful authenticated navigation were not exercised end to end. |
| Agent tools and execution reliability | **Partially verified.** `tests/test_harness_runtime.py`, `tests/test_parallel_tool_calls.py`, `tests/test_network_tool_cancellation.py` and `tests/test_security_approval_resume.py` ran. The model error-generator defect remains. Live model/tool services were not called. |
| Database consistency and concurrency | **Partially verified.** `application/operations.py` uses `BEGIN IMMEDIATE` for admission; `agent/todos/service.py` uses SQLite transactions; `tests/test_shared_db_recovery.py`, `tests/test_todos.py` and `tests/test_harness_runtime.py` cover migration, recovery and leases. No multi-process stress test or real-database migration ran. |
| Permissions and security | **Partially verified.** The suite includes gateway, Security Center, path traversal, SSRF and browser request-scope tests. Source review found Electron permission and navigation concerns below; exploitability was not tested. No live penetration scan ran. |
| UI interaction and experience | **Partially verified.** The Playwright login error interaction passed. Navigation, accessibility, keyboard use and responsive layouts across remaining pages were not measured. |
| Performance and resource use | **Limited review.** Source contains browser idle timeout (`agent/tools/browser/browser_service.py`) and backend request limits (`desktop/src/main/http-relay.ts`). Pytest took 36.14 seconds in the final full run. No load, memory or battery benchmark ran. |
| Exception recovery and stability | **Partially verified.** Full-suite cases cover shared-database recovery, SSE replay/cancellation and scheduler uncertain outcomes. The model exception path reproduced below fails while reporting an earlier error. |
| Core business flows and regression | **Partially verified.** Todo hierarchy/reminders, briefing partial failure, billing, calendar and scheduler tests ran in the 1265-passing suite. External mail, eLearning, channel delivery and provider calls were intentionally not exercised with real accounts. |

## Confirmed issues

### 1. Model error generators raise a second exception

- **Severity:** Medium. An API/setup error in affected adapters is reported as `NameError` instead of a structured error, obscuring the original cause and potentially breaking streaming recovery.
- **Locations:** `models/claudeapi/claude_api_bot.py:438`, `models/deepseek/deepseek_bot.py:303`, `models/doubao/doubao_bot.py:269`, `models/linkai/link_ai_bot.py:644`, `models/mimo/mimo_bot.py:292`, `models/minimax/minimax_bot.py:294`, `models/moonshot/moonshot_bot.py:319`.
- **Cause:** Each nested generator reads `e` after leaving `except Exception as e`. Python clears that exception variable at the end of the handler; generator execution happens later.
- **Safe reproduction:** In an isolated Python process, create a MoonshotBot without network setup, patch `_convert_messages_to_openai_format` to raise `RuntimeError("offline sentinel")`, call `call_with_tools([], stream=True)`, then `next(result)`. Observed: `NameError free variable 'e' referenced before assignment in enclosing scope`. `.venv/bin/ruff check --select F821 models` also identifies the seven locations.
- **Suggested fix:** Capture the message in a local variable before defining the generator, then add failure-path tests for each adapter family. Business code was left untouched under the audit rule.

### 2. Full-repository static gate is red

- **Severity:** Medium for maintainability and release confidence. Ruff reports 492 findings, so this full static gate cannot currently pass.
- **Locations:** For example `channel/chat_channel.py:8` (`F403` star import), `channel/chat_channel.py:46` (`F405` possibly undefined name); see the Ruff command above for every location. The file has 152 findings; rule totals include `F405` 190, `F401` 96, `E402` 58, `F541` 50, `F841` 26 and `F821` 7.
- **Reproduction:** Run the full Ruff command in the automated evidence table; exit code is 1 and output ends `Found 492 errors.`
- **Suggested fix:** Address runtime-affecting `F821` cases first, then clean or explicitly baseline legacy import/style findings in focused batches. Do not mask this gate as passing. No bulk auto-fix was applied.

## Potential risks requiring follow-up verification

1. **Electron permission scope:** `desktop/src/main/index.ts:582` grants every Chromium permission request through one callback. Source confirms the blanket grant; impact depends on which origins can load and request permissions. Verify with an Electron integration test for microphone and an unrelated permission, then restrict grants to the intended requesting window and permission.
2. **External URL handling:** `desktop/src/main/index.ts:176-177` passes a window-open URL to `shell.openExternal` without an observed scheme allowlist, while `:184-188` blocks only `file:` navigation to a different file. Test untrusted/invalid schemes with a mocked Electron shell and inspect renderer-controlled URL paths before assigning exploit severity.
3. **Python version support:** `pyproject.toml:9` declares Python `>=3.7`, while `tests/test_evolution_safety.py:167` and `tests/test_evolution_trigger.py:44` use parenthesized `with` syntax Ruff flags as invalid for Python 3.7. A clean Python 3.7 install/test matrix is needed; this audit used Python 3.9 only.
4. **End-to-end coverage:** The Playwright smoke tests only login rejection, and external integrations used mocks. Run representative authenticated page workflows, keyboard/accessibility checks and opt-in staging-account delivery tests with disposable accounts before a release that changes those areas.

## Unexecuted checks and limits

- No Semgrep or ESLint run: the project has no existing configurations for them, and Ruff, Python tests, TypeScript checks and focused browser tests cover the current local quality gate. This does not imply equivalent security or JavaScript lint coverage.
- No Windows test run, Python 3.7/3.11 matrix, live provider/channel/eLearning integration, production-data migration, long-running concurrency/load test, accessibility audit or packaged Electron application test. These remain **SKIP**, not PASS.
- Static source review cannot establish that a possible Electron permission or URL issue is exploitable. Both are listed as risks, separately from reproduced defects.

## Remediation after this audit

On `codex/recover-audit-and-todo-lock-20261008`, the seven model error-generator defects above were fixed with offline regression coverage in `tests/test_model_error_generators.py`. The todo scheduler backfill was also changed to avoid redundant writes and to defer maintenance when SQLite reports a transient write lock; `tests/test_todos.py` covers the deferred and recovery paths. A subsequent isolated full check found **1275 passed, 4 skipped, 1 warning** in pytest, with desktop typecheck, Node, and Playwright checks passing. Full-repository Ruff remains **FAIL** with 472 findings, down from the original 492; those remaining findings were not bulk-edited. This note records later work and does not alter the audit's original baseline results or its remaining potential risks.
