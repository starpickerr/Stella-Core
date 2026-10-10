# Briefing Generation Implementation Plan

> **For Stella workers:** Use the project `executing-plans` skill to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking; tests use isolated project data.

**Goal:** Remove in-run previews and make the first decision submission and any correction use the same fetched candidates with complete, actionable validation rules.

**Architecture:** `BriefingPipeline` owns one fetch/stage/finalize pass; `AgentBriefingGenerator` owns the batch prompt and result tool. Keep previously saved out-of-window decisions and the current commit/cursor boundary. The model may retry the result tool inside the same batch, but the pipeline never fetches again for a formatting error.

**Tech Stack:** Python, SQLite, pytest, scripted model fixtures.

**Spec:** [Stella current requirements](../../../.agents/task/requirements.md#1-简报生成).

## Global Constraints

- Do not read or modify the real `briefing.db`, connect real accounts, or call a real model in tests.
- Preserve prior saved briefing, source cursors, cancellation, partial-source semantics, and no keyword fallback.
- Hard validation remains exact ID coverage, boolean `selected`, nonempty `reason`, and selected `section`/integer `score`/nonempty `summary`.
- `category` and `information_type` remain requested model output but are not independent rejection conditions.

## Review Focus

- One source fails while another succeeds: `tests/test_briefing_pipeline.py` must still cover partial output and cursors.
- A saved out-of-window item survives an update: `tests/test_briefing_daily.py` must pin reuse.
- The model omits, duplicates, or invents an ID: `tests/test_briefing_agent.py` must report which IDs are wrong.
- `selected=true` with a boolean score or empty summary: `tests/test_briefing_agent.py` must reject and explain it.
- Cancellation during a retry: `tests/test_briefing_agent.py` must stop without replacing the saved result.

---

### Task 1: Remove the preview pass

**Files:** Modify `agent/briefing/pipeline.py`, `agent/briefing/generator.py` if `preview()` becomes unused, `agent/briefing/progress.py` only if the progress contract requires cleanup; test `tests/test_briefing_pipeline.py`, `tests/test_briefing_agent.py`.

**Interfaces:** `BriefingPipeline.run()` still calls `generator.generate(rows, rules, ..., preserved_decisions=...)` once after fetching. `preserved_decisions` contains only saved out-of-window history, not judgments from this run's preview.

- [ ] Write a test with multiple `StaticSource` instances and a recording generator: no `preview()` call, one `generate()` call after all fetches, and saved out-of-window decisions passed through.
- [ ] Run the targeted test through `scripts/run_isolated.py`; confirm it fails on the current preview worker behavior.
- [ ] Remove `_PreviewWorker`, early preview callbacks/merging, and the blocking `preview.close()` path. Keep staged source snapshots, progress updates, error handling, and final catalog assembly.
- [ ] Run `tests/test_briefing_pipeline.py tests/test_briefing_daily.py tests/test_briefing_agent.py` in isolation; confirm PASS.
- [ ] Review the diff for leftover `draft-preview` progress or unused preview methods, then commit this logical change.

### Task 2: Show the complete contract before the first decision call

**Files:** Modify `agent/briefing/generator.py`; test `tests/test_briefing_agent.py`.

**Interfaces:** A batch task passed to `_run_agent(...)` contains `expected_ids` as an exact list and the complete hard validation contract. `validate_decisions(payload, expected)` remains the authoritative runtime check. Keep tool schema and prompt aligned through a shared helper or a test that asserts their consistency.

- [ ] Add a scripted-model test that inspects the first decision request for all batch IDs and every rule in the spec; assert `category`/`information_type` appear as requested output and that excluded items need no selected-only fields.
- [ ] Run that test and confirm it fails because the current task does not list or explain every hard condition.
- [ ] Build the decision task from the current batch IDs and explicit validation text; express supported requirements in the tool schema without requiring meaningless selected-only fields on excluded items.
- [ ] Run the new test and current decision tests; confirm PASS. Commit this logical change.

### Task 3: Return actionable errors and correct without refetching

**Files:** Modify `agent/briefing/generator.py`; test `tests/test_briefing_agent.py`, `tests/test_briefing_pipeline.py`.

**Interfaces:** `ResultTool.execute()` returns a failure with missing/duplicate/unknown IDs or `(id, field, expected)` details. The same `_run_agent` batch keeps the candidate snapshot and rule text. A rejected result does not alter store, cursor, or source fetch count.

- [ ] Add tests for missing/duplicate/unknown IDs and invalid `selected`, `reason`, `section`, `score`, `summary`; inspect the tool result text for exact repair guidance without candidate body content.
- [ ] Add a scripted sequence: first decision submission invalid, second corrected, then body; assert the source's `fetch()` was called once and the completed briefing contains the corrected result. Add a failure/cancellation case that preserves the last saved revision and cursor.
- [ ] Run those tests and confirm each fails for the intended current behavior.
- [ ] Return structured, precise validation messages; keep the existing batch context for resubmission, with only the result tool needed for format repair. Do not call pipeline source adapters again or supply defaults for missing fields.
- [ ] Run targeted briefing tests; confirm PASS. Commit this logical change.

### Final gate

- [ ] Run `.venv/bin/python scripts/quality_check.py incremental` using isolated test data; record PASS/FAIL/SKIP and any concrete limitation below.
- [ ] Inspect `git diff` and compare every requirement in the linked spec with code and tests. Record final commit(s); do not treat this plan checkbox as completion evidence.

## Progress

- Status: implemented on `fix/briefing-generation-20261010`. Preview generation is removed. The decision task lists `expected_ids` and the hard rules, and the tool schema requires section, score, and summary only when `selected` is true.
- Verification: PASS isolated pytest `tests/test_briefing_pipeline.py tests/test_briefing_daily.py tests/test_briefing_agent.py` — 40 passed.
- SKIP final incremental quality check until the knowledge-link plan in this iteration is included.
