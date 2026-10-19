# Stella-Plugins workspace (local staging)

This tree mirrors the future [Stella-Plugins](https://github.com/starpickerr/Stella-Plugins) repository layout while the mainline lands in Stella.

| Plugin | Role |
| --- | --- |
| `plugins/bills` | First business vertical (`stella.bills@1`) |
| `plugins/calendar` | Calendar vertical (`stella.calendar@1`); Apple sync stays in Core |
| `plugins/tasks` | Tasks vertical (`stella.tasks@1`); reminder sync is host-reconciled |
| `plugins/email` | Email vertical (`stella.email@1`); owns IMAP credentials, folders and cursors |
| `plugins/elearning` | eLearning vertical (`stella.elearning@1`); discover/read/background/sync are separate purposes |
| `plugins/briefing` | Briefing vertical (`stella.briefing@1`); sources come from Core SourceDirectory, todo/calendar-bound actions are bridged host-side |
| `plugins/automation` | Automation vertical (`stella.automation@1`); task rules/mutations/handler planning, Core keeps lease/dispatch/delivery |
| `plugins/mcp-echo` | Lightweight MCP-only package (no runtime/UI/data) |

Publishable ZIP/catalog/signing belong to stage D; until then Core loads these paths via `STELLA_BILLS_PLUGIN_ROOT` / package ops.
