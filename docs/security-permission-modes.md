# Permission modes and execution boundary

## Request path

Chat tool calls enter `AgentStreamExecutor`, direct tool calls enter `BaseTool`, and scheduled calls enter `scheduler.integration`. Each calls `permission_denial` before executing a tool. It resolves the current RuntimeIdentity, project, session preference, global policy, working directory, roots, tool allowlist, and account allowlist. `SecurityGateway` classifies the operation, applies all relevant rules, records an audit decision, and either allows, denies, or creates an interactive one-use approval. After approval, the waiting call resolves the inputs again and stops if any binding changed. The original call then resumes once. Subagents inherit a rule and root ceiling from the parent run.

The desktop Security Center and chat composer use the backend's `mode_definitions`; they save global, project, and conversation differences through the existing stores. A conversation without a project uses the user's `work` directory. Agent memory, skills, credentials, and scheduler state remain in their existing state directories.

## Modes and migration

| Mode | Normal work | Scope outside the workspace |
| --- | --- | --- |
| `read-only` | Authorized reads run; unauthorized writes are denied | Deny |
| `workspace-write` | Create, change and delete in the current workspace | Confirm |
| `full-access` | Ordinary file and shell limits are relaxed; other chats' private Work, managed data, credentials and Apple grants stay blocked | Allow; important external and destructive actions still require confirmation |
| `custom` | Saved rule snapshot copied from the effective mode | Determined by saved rules |

Fresh installs use `workspace-write`. Stored `approval` becomes a Custom snapshot of its confirm-on-write rules. Stored `project-full` is Workspace Write. `strict`, `standard`, and a bare legacy `custom` name remain exact custom snapshots. A damaged policy fails closed and reports an error. Corrupt project or conversation stores fail closed rather than silently resetting their contents.

## Process and browser enforcement

On macOS, shell foreground and background processes use Seatbelt to restrict writes to authorized roots and a dedicated temporary directory. An approved outside file opens only that exact path for one call. Protected credential and control paths are denied for reads and writes. On Linux, bubblewrap mounts the filesystem read-only in constrained modes, binds authorized writable roots, and masks protected paths. Both backends probe actual launch ability; if unavailable, shell execution fails with a clear error. Windows reports unavailable and does not claim process isolation. Child processes inherit the OS boundary and receive the existing filtered environment.

The browser gate separately checks navigation, local files, and interactions. A context route checks requests, redirects, and subrequests against the cloud metadata guard and current file scope. Browser interaction and unknown MCP side effects require confirmation. MCP public tool names include a server identity, so identical remote names cannot share a policy identity.

## Operational limits

- Seatbelt currently enforces **writes** outside the workspace and protects known credential and control paths. It does not provide a general read-only mount view of every unrelated macOS directory. Linux's read-only root mount likewise allows reading ordinary unrelated files. The gateway checks paths used through file tools and browser local navigation; shell scripts can read unrelated ordinary files that are not protected paths.
- Linux's exact one-file outside grant requires that the target already exists. Creating a new outside file needs an explicit directory grant; the sandbox refuses to widen a one-file approval into a directory grant.
- Running background processes retain their launch sandbox. Changing a policy governs later tool calls and does not retroactively stop a process already started. Background process query and stop operations check the recorded owner.
- DNS is checked before browser requests, but IP addresses are not pinned between DNS resolution and connection. Browser DNS rebinding remains a network boundary limitation.
- Scheduled calls that need approval stop with `pending_approval`. They create no reusable approval token or automatic retry. The user must adjust policy and manually rerun the task, which creates a new recorded run.

## Verification

Run `.venv/bin/python scripts/quality_check.py full --report /tmp/stella-quality-report.md` from the repository root. Checks run with temporary HOME and STELLA_DATA_DIR. The process sandbox tests execute a real project write and a blocked outside write when the platform backend is available.
