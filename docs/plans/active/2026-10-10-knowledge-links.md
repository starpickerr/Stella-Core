# Knowledge Links Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Restore knowledge document navigation after the Markdown renderer change and resolve relative paths without opening an unrelated same-name file.

**Architecture:** `Markdown` chooses a link target based on its host context: when the knowledge page provides `onInternalLink`, relative Markdown documents use that callback before generic workspace preview routing. A pure knowledge path resolver receives the current document path and tree and resolves exact targets inside the knowledge root. UI reports unresolved links.

**Tech Stack:** React, TypeScript, node:test, Playwright.

**Spec:** [Stella current requirements](../../../.agents/task/requirements.md#2-知识库索引跳转).

## Global Constraints

- Preserve chat workspace-file preview links and external URL behavior.
- Do not disable `safeUrl` or allow an escaped relative path outside the knowledge root.
- Use isolated browser data; no real knowledge files need editing.

## Review Focus

- `assessment/software-design.md` from `index.md` must take the knowledge callback, not workspace preview.
- `./README.md` from a nested document must stay in its directory, even when other `README.md` files exist.
- `../x.md` must normalize correctly; `../../` outside the root must be refused.
- Query/fragment suffixes must not change target resolution; a missing target must show a visible error.
- Absolute web links and unsafe schemes must retain safe existing behavior.

---

### Task 1: Restore knowledge-link precedence in Markdown

**Files:** Modify `desktop/src/renderer/src/components/Markdown.tsx`; test `tests/renderSafety.test.mjs` or a focused renderer test and a new isolated Playwright knowledge scenario.

**Interfaces:** `Markdown({ onInternalLink })` invokes the callback for a safe, relative `.md` href before calling `workspaceHrefOf`. Without the callback, `workspaceHrefOf` continues to route chat links to preview.

- [ ] Add a failing interaction test that renders `[软件设计](assessment/software-design.md)` with `onInternalLink`, clicks it, and asserts callback invocation and no workspace-preview call; add a case without the callback that still previews a workspace file.
- [ ] Run the focused test; confirm failure on the current `workspaceHrefOf`-first order.
- [ ] Route safe relative Markdown links to `onInternalLink` first; retain URL sanitization and external links.
- [ ] Run focused node/browser tests and confirm PASS. Commit this logical change.

### Task 2: Resolve exact knowledge paths

**Files:** Modify `desktop/src/renderer/src/pages/KnowledgePage.tsx`; create `desktop/src/renderer/src/pages/knowledgeLinks.ts` if extracting the pure resolver simplifies testing; test `tests/knowledgeLinks.test.mjs` and the browser scenario.

**Interfaces:** `resolveKnowledgeLink(list, currentPath, href)` returns the exact tree target `{path, title}` or `null`. It normalizes relative paths against the current document, accepts a `knowledge/` root prefix, and never chooses the first matching basename. `openInternalLink` passes `activePath` and displays an error when the target is absent or outside the root.

- [ ] Write resolver tests for the four path cases in Review Focus, including two directories with `README.md`, query/fragment suffixes, and a nonexistent link; run to confirm failures.
- [ ] Replace basename fallback with exact normalized path lookup; pass current document path from `KnowledgePage`; surface a concise message for unresolved/unsafe paths.
- [ ] Run resolver tests and the browser scenario: click the “软件设计” link from `index.md`, verify `assessment/software-design.md` opens. Confirm PASS and commit.

### Final gate

- [ ] Run `.venv/bin/python scripts/quality_check.py incremental` and the affected browser interaction against isolated data; record PASS/FAIL/SKIP.
- [ ] Recheck the root-cause diff against `fdaa35ef` and ensure unrelated Markdown rendering still works. Record final commit(s).

## Progress

- Status: implemented on `fix/briefing-generation-20261010`. Relative Markdown links in the knowledge page use the knowledge callback before workspace preview. Exact paths replace the first-basename fallback, and a missing target shows “找不到这篇知识文档”.
- Verification:
  - PASS `node --experimental-strip-types --test tests/knowledgeLinks.test.mjs` — 2 passed.
  - PASS isolated `tests/ui_knowledge_links.py`: clicking “软件设计” in `index.md` shows the software-design document.
  - PASS `npx tsc --noEmit -p desktop/tsconfig.json` before the browser run.
