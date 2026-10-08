# Stella development instructions

## Branch and data safety

- Before changing project code or configuration, create a dedicated branch from the current development baseline. Do all work and commits on that branch. Change `develop` only when the user explicitly asks to merge or update it.
- Preserve existing code, data, and uncommitted edits. Run tests with temporary `HOME`, `STELLA_DATA_DIR`, and workspace data. Never aim audit tools at real user databases, credentials, or external services.

## A: routine development verification

- Inspect the diff and map changed files to affected modules and their tests. Use `.venv/bin/python scripts/quality_check.py incremental` as the default automated gate. The script selects targeted Ruff, pytest, TypeScript, Node, and browser checks according to changed paths.
- Add focused tests for changed behavior. Agent tools, permission, state, database, concurrency, and migration changes need targeted failure and recovery cases. For UI changes, exercise the affected interaction with Playwright in addition to typechecking; extend `tests/ui_smoke.py` or write a focused browser test when the generic smoke cannot cover the change.
- If a check fails, reproduce and locate the cause, fix the relevant code, then rerun the failed and affected checks. Follow `systematic-debugging`, `test-driven-development`, and `verification-before-completion` skills as appropriate. Use `requesting-code-review` for major changes when a reviewer is available.
- Before delivery, compare behavior with the request, review the diff for regressions, and report PASS, FAIL, and SKIP separately. Do not claim an unrun check passed. Run the full suite only when the scope or risk warrants it.

## B: Full Audit

- On `Full Audit` or `全项目体检`, load `.agents/skills/software-audit/SKILL.md` and run its complete workflow. This is a manual, report-producing request, not the daily incremental gate.
- Default to detection and a structured Markdown report. Do not change business code during Full Audit unless the user explicitly requests fixes. Keep confirmed issues distinct from potential risks and mark any unexecuted checks accurately.
