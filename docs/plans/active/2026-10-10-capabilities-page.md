# Capabilities Page Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Rename the skills page to Capabilities and show the full built-in tool catalog in both languages, folded until the user expands it.

**Architecture:** A catalog module lists every built-in tool id with zh/en title, intro, and detail, plus an availability reason. The API returns that catalog. The page renders it; it does not change which tools an agent receives.

**Tech Stack:** Python tool registry, React, node tests, Playwright.

**Spec:** `.agents/task/requirements.md` section 6 and `.agents/task/capabilities.md`.

## Global Constraints

- Route stays `/skills`. Labels are 能力 / Capabilities.
- Catalog includes `memory_search` and `memory_get` and excludes MCP tools.
- Missing availability still lists the tool with a localized reason.
- Copy comes from the catalog, never from the agent `description`.
- Entries start collapsed. Expansion does not toggle a skill. Details use `/skills/tools/:id` and `/skills/skills/:id`.
- A failed request shows an error and retry, not an empty catalog.

## Review Focus

- A tool skipped because an optional dependency is missing remains in the catalog with that reason.
- Switching language updates an already expanded card and an open detail page without changing the id.
- Long text has no `line-clamp` truncation.
- Listing a tool does not add it to `ToolManager.tool_classes`.

---

### Task 1: Catalog and API

**Files:**
- Create: `agent/tools/catalog.py`
- Modify: `channel/desktop/desktop_channel.py` `ToolsHandler`
- Test: `tests/test_tool_catalog.py`

- [ ] Assert the catalog ids equal the built-in classes in `agent/tools/__init__.py` `__all__`, excluding `BaseTool`, `ToolManager`, and `McpTool`, and including both memory tools once.
- [ ] Assert every id has nonempty zh and en title, intro, and detail, and the payload has no credential or agent-description field.
- [ ] Run and confirm FAIL, then implement. Unavailable tools stay listed with `available: false` and a localized `reason`.
- [ ] Run the test and confirm PASS.
- [ ] Commit.

### Task 2: Page

**Files:**
- Modify: `desktop/src/renderer/src/pages/SkillsPage.tsx`
- Modify: `desktop/src/renderer/src/App.tsx`
- Modify: `desktop/src/renderer/src/i18n.ts`
- Modify: `desktop/src/renderer/src/layout/NavRail.tsx`
- Test: `tests/ui_capabilities.py`

- [ ] Browser test: sidebar and title say 能力; cards start collapsed; expanding `memory_search` shows the full Chinese intro and a detail link; skill toggle still works and is not fired by expanding.
- [ ] Run and confirm FAIL.
- [ ] Implement folded cards, detail routes, localized copy, and separate error states for tools and skills.
- [ ] Run the UI test and confirm PASS.
- [ ] Commit.
