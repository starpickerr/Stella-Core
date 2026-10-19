# Stella-Plugins workspace (local staging)

This tree mirrors the future [Stella-Plugins](https://github.com/starpickerr/Stella-Plugins) repository layout while the mainline lands in Stella.

| Plugin | Role |
| --- | --- |
| `plugins/bills` | First business vertical (`stella.bills@1`) |
| `plugins/mcp-echo` | Lightweight MCP-only package (no runtime/UI/data) |

Publishable ZIP/catalog/signing belong to stage D; until then Core loads these paths via `STELLA_BILLS_PLUGIN_ROOT` / package ops.
