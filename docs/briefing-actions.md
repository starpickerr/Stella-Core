# Briefing decisions and quality checks

Briefings collect and explain changes. Tasks own completion, hierarchy and planning;
calendar events own activity times; the scheduler owns reminder delivery. Reading a
briefing never completes a task. Submitted and graded are retained as source facts.

## Decisions

New action cards are suggestions. Importance, a deadline or an AI classification
does not create a task or event. Confirm **Create task**, search **Link existing**,
or choose briefing only, defer or ignore. Creation can specify a title, parent,
planned date, deadline and reminder. A deadline creates no calendar event. Events
require actual start and end times and confirmation of inferred times.

Linked cards read the current business object, independently of the original
snapshot and reading state. They expose actual creation/synchronization receipts,
conflicts, failures and retries. **Confirm update** accepts new source facts;
**Keep current** retains the user value until another source change. Edit a linked
object through its task/calendar page. Unlinking or deleting an object prevents
automatic recreation. Explicitly linking another existing object resumes tracking.

Scoped handling rules live in briefing settings. A rule identifies the source,
account, information type, optional course, operation and handling mode. One-time
confirmation grants no ongoing permission unless the separate checkbox is chosen.
Rules are editable by saving the same scope and can be revoked. Source deadlines
and activity times synchronize existing links by default, with field conflicts
protected; a `sync` rule can require confirmation or disable synchronization.

Reminder authorization specifies minutes before the source deadline. It needs a
linked active task and creates a scheduler task, without a calendar event. Explicit
user reminder edits, including clearing a reminder, are preserved. Source-owned
reminders adjust with deadlines and cancel when the source removes its deadline.
Scheduler configuration failures are distinct from task creation success and can
be retried. Configuration success is not a claim of notification delivery.

## Identity, history and recovery

Native assignment and grade IDs map to one entity. Email references use a stable
thread root; exact legacy message keys are adopted without deleting old objects.
Equal titles offer candidates for user confirmation rather than automatic merging.
Cross-source uncertain matches can be linked by the user. Selected thread sources
fold chronologically so a higher-scored older card cannot suppress a later change.

Business creation uses a stable key inside the task/calendar transaction. If the
process stops after business commit and before receipt commit, retry recovers the
exact target. Legacy tombstones and current deletion/detachment state are honored.
Each outbox consumer preserves its own acknowledgement. A saved failure receipt
is recoverable by retry without regenerating sources or undoing successful writes.

The decision schema is additive. It preserves business objects, immutable briefing
revisions, source cursors and legacy data. User title, plan, progress and completion
are never overwritten by external facts. Explicit user deadlines/time choices have
source baselines so later changes request confirmation instead of overwriting them.

Incremental cards emphasize new/changed facts, failures and approaching deadlines.
The full overview reads latest tracked entities across dates, without generation,
cursor advancement or projection writes. Old revisions keep their saved text/cards;
the linked business state is current. Display preferences change visibility, ongoing
frequency, priority types and summary expansion; they do not grant write permissions.

## Agent and API

`briefing` exposes `get`, `overview`, `targets`, `decide`, `action_rules`, `authorize`,
`revoke_authorization`, `preferences` and `set_preferences`. The desktop API delegates
to the same service. All HTTP operations require authentication; read-only Agents
cannot make decisions or authorizations. For example, use `get` to find an item ID,
then `decide` with `{"operation":"create","kind":"todo"}` to create only a task.

## Daily checks and Full Audit

Install project dependencies with `.venv/bin/python -m pip install -r requirements-dev.txt`
and `npm --prefix desktop ci`. The five upstream development skills and Stella's
audit skill are in `.agents/skills/`; they are discovered by Codex in this project.

Use `.venv/bin/python scripts/quality_check.py incremental` during development.
`--files` selects an explicit scope. The runner maps changed modules to Ruff,
pytest, desktop ESLint, TypeScript, build, Node and Playwright checks. Each result
is printed as PASS, FAIL or SKIP, with failure output. State and provider environment
are isolated in temporary directories. UI checks launch a private renderer and
exercise login rejection plus real React briefing interactions with a mocked backend.
Python handler tests exercise actual isolated SQLite services.

Say **Full Audit** or **全项目体检** to invoke the report workflow. Its automated
portion is `.venv/bin/python scripts/quality_check.py full`; a timestamped report
appears in `.agents/audits/code-review/`, preserving previous reports. Source review completes
the domain matrix and separates reproduced issues from potential risks and skips.
Audits do not repair business code. Request fixes explicitly after reviewing a
report. Historical static failures remain failures and are not hidden or relabeled.

On Windows use `.venv\Scripts\python.exe` for the commands above. The check runner
redirects HOME, USERPROFILE, APPDATA, LOCALAPPDATA and temporary directories, resolves
native executables and cleans up its private renderer tree. Native Windows execution
still needs verification on a Windows host.

External account integrations, native packaged Electron behavior, cross-platform
execution and prolonged load require additional dedicated environments. Mocked
browser success does not prove those integrations work with live services.
