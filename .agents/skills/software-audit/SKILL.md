---
name: software-audit
description: Run a complete, read-only Stella software audit when the user says "Full Audit" or "全项目体检"; produce an evidence-based Markdown report.
---

# Stella Full Audit

Use this skill only for an explicit full-project audit request. The default deliverable is a report, without changes to business code.

1. Confirm the current branch and diff. Preserve the user's work. Identify current architecture and all core flows from source and tests. Note any areas that cannot be exercised offline.
2. Run `.venv/bin/python scripts/quality_check.py full` from the repository root. It executes Ruff, pytest, desktop TypeScript checks, Node tests, and a Playwright interaction with temporary state. The script writes `audit-reports/Full-Audit-YYYY-MM-DD.md`. A failed check remains failed; investigate it before drawing conclusions.
3. Review each domain, using code and focused reproduction when feasible: code defects; architecture and dependencies; backend and desktop functions; Agent tool execution and cancellation; SQLite migrations, transactions, and concurrency; permissions, secrets, input boundaries, and SSRF; UI interaction and accessibility; performance and resource use; exception recovery; and main business flows. Inspect the relevant source and tests rather than assuming a passing test proves a domain sound.
4. Complete the report's domain matrix. For each confirmed issue, include severity, exact file and line, symptom, safe reproduction, cause, fix recommendation, and command/output evidence. Put uncertain concerns under potential risks with a concrete verification method. Record untested areas and reasons. Never relabel an unrun or failed check as passed.
5. Review the finished report for accuracy and avoid including credentials or real user data. Do not fix business issues without an explicit follow-up request. The audit harness itself may be repaired and rerun if it is broken.

Install audit dependencies only in Stella's local `.venv` or `desktop/node_modules`. Never install skills globally for this workflow. Prefer existing tests and the project-level `webapp-testing` skill for browser tests.
