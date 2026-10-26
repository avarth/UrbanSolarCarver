# Criteria step rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Criteria step keeps its list of criteria on screen at all times (also with one criterion), each row has an "on" switch that is on by default, the selected criterion's panel is folded into short sections with one-line summaries, a new criterion's mode is chosen from a short menu, and Run analysis and Build envelope and massing sit in the pinned bar at the bottom of the step.

**Architecture:** App-only change (`app/`). `CriteriaStep` always renders `CriterionList`; `CriterionCard`'s switch shows `!bypassed`; `CriterionPanel` wraps its four parts in a new `PanelSection` (button header with title and summary, `aria-expanded`); `AddCriterion` opens a new `ModeMenu` instead of the tile grid; the Criteria step's pinned action (the existing `.step-pinned-action` area of `StepAccordion`) holds Run analysis with its progress and the build button. The service and the data model do not change (`bypassed` stays the stored field).

**Tech Stack:** TypeScript, React 19, vitest with jsdom (`renderForTest`, `FakeService` / `ChainService` stubbing `fetch`).

**Spec:** `vault/features/chained-carvings.md`, section "Criteria step rework (user, 2026-10-26, after trying phase 3)", agreed with the user on 2026-10-26; `docs/superpowers/specs/2026-10-25-chained-carvings-design.md` section 7.2 for the card contents. The rework supersedes the phase 3 rule "one criterion shows no list chrome".

## Global Constraints

- The word stays "criterion" / "Criteria" everywhere in the UI (user, 2026-10-26): step title "Criteria", button "Add criterion".
- The list of criteria is always shown, also with one criterion; new projects start with one criterion in it (the service already creates criterion "1").
- Each row's switch means "on": checked = the chain uses the criterion; new criteria are on. Unchecked rows read "Off" in the status line; no "Bypass" wording remains in the UI.
- No per-row run button; one Run analysis traces only what changed (as today).
- The panel's sections, in order: Test surfaces, Mode, Settings, Carving rule. Test surfaces and Carving rule start open; Mode and Settings start closed.
- Run analysis (with its run progress and refusals) and Build envelope and massing are in the Criteria step's pinned bar, not in the panel.
- All strings in `app/src/messages.ts` (plain words, no em dash, no "plate"; function messages accept numeric arguments, `messages.test.ts` calls them with `(1, 2, 3, 4)`). Short labels without a final period, as the existing run reasons.
- A commit that changes `app/` also commits the rebuilt `src/urbansolarcarver/ui_static`.
- App test tiers: `npx vitest run <file>` while editing; `npm test && npm run build` before each commit; the Python `-m "not sweep" -n 8` tier once at the end (packaging test).

## Review Focus

- A run refused for a criterion's setting whose section is closed: "Go to <setting>" opens that section and focuses the field. Pinned in Task 2.
- A criterion with no test surfaces: its Test surfaces section is open, its summary says so, and the pinned Run analysis says what is missing. Pinned in Task 2 and Task 4.
- Turning the only criterion off: its row reads "Off", Run analysis waits with "Turn on a criterion to run", turning it back on restores the panel. Pinned in Task 1.
- A long run progress list in the pinned bar on a short window: the bar scrolls within its height and the step above stays reachable. Pinned in Task 4.
- Selecting another criterion keeps the user's open and closed sections (the choice belongs to the step, not to one criterion), except that a section with a problem opens. Pinned in Task 2.

---

## File structure

- `app/src/criteria/CriteriaStep.tsx`, `CriterionList.tsx`, `CriterionCard.tsx`, `CriterionPanel.tsx` (Tasks 1, 2, 4).
- `app/src/criteria/PanelSection.tsx` (new, Task 2); `app/src/criteria/section_summaries.ts` (new, pure, Task 2).
- `app/src/criteria/ModeMenu.tsx` (new, Task 3).
- `app/src/steps/ProjectWorkspace.tsx`, `app/src/steps/result_steps.tsx` (pinned actions, Task 4), `app/src/criteria/use_workspace_criteria.ts` (as needed).
- `app/src/messages.ts`, `app/src/steps/steps.css`.
- Docs: `docs/ui.md`, `CHANGELOG.md` (Task 5).

---

### Task 1: The list is always there; the switch means on

**Files:**
- Modify: `app/src/criteria/CriteriaStep.tsx`, `CriterionList.tsx`, `CriterionCard.tsx`, `CriterionPanel.tsx` (remove `TurnOnCriterion`), `app/src/steps/result_steps.tsx` (the bypassed note), `app/src/messages.ts`, `app/src/steps/steps.css`
- Test: `app/src/criteria/CriteriaStep.test.tsx`, `CriterionCard.test.tsx`, `CriterionList.test.tsx`, `app/src/steps/ProjectWorkspace.criterion_cards.test.tsx`, `ProjectWorkspace.criteria.test.tsx`

**Interfaces:**
- Produces: `CriteriaStep` renders `CriterionList` for any number of criteria (0 cards only while a project has none, which the service does not produce), then the chain line (two or more criteria, as today), then the panel. "Add criterion" (`messages.addCriterion`) sits under the last card in every state; `messages.addAnotherCriterion` is removed.
- Produces: `CriterionCard` switch `checked={!entry.bypassed}`, `aria-label={messages.criterionSwitchLabel(name)}` ("Use {name}"; not named `use...`, which lint would read as a React hook), `onChange` calls `onSetBypassed(!event.target.checked)`; the drag handle is not rendered when the list has one card (`CriterionListProps` passes `reorderable: boolean`).
- Messages: `criterionBypassed` "Bypassed" -> `criterionOff` "Off"; `criterionBypassedNote` -> `criterionOffNote` "Off: the chain skips this criterion" (shown in place of the carving rule of a selected criterion that is off); `bypassCriterion` -> `criterionSwitchLabel`; `turnOnCriterion` and `TurnOnCriterion` removed (the switch is always visible now).

- [ ] **Step 1: Write the failing tests**: `test one criterion shows its row in the list` (one card with swatch, name, line, switch checked; no drag handle; Delete disabled with "A project needs at least one criterion."), `test the switch is on for a criterion the chain uses` (checked for `bypassed: false`; unchecking sends `PATCH /criteria/1` with `{bypassed: true}`), `test a criterion switched off reads Off` (row line "Off", panel note "Off: the chain skips this criterion"), `test turning the only criterion off and on again` (Run analysis waits with "Turn on a criterion to run"; checking the switch restores the carving rule), `test add criterion sits under the list with one criterion`, `test a new project opens with one criterion in the list` (App flow: create a project, open the Criteria step: one row, switch on); invert the existing tests that asserted no list chrome or "Add another criterion" or "Bypass {name}".
- [ ] **Step 2: Run them to verify they fail** (`npx vitest run src/criteria src/steps/ProjectWorkspace.criterion_cards.test.tsx src/steps/ProjectWorkspace.criteria.test.tsx`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): the criteria list stays on screen; each criterion's switch means on`.

---

### Task 2: The panel in folded sections

**Files:**
- Create: `app/src/criteria/PanelSection.tsx`, `app/src/criteria/section_summaries.ts` (+ tests beside them)
- Modify: `app/src/criteria/CriterionPanel.tsx`, `app/src/criteria/CriteriaStep.tsx` (open state), `app/src/steps/SettingsStep.tsx` / `result_steps.tsx` (go to setting), `app/src/messages.ts`, `app/src/steps/steps.css`
- Test: `app/src/criteria/CriterionPanel.test.tsx`, `ProjectWorkspace.saves_and_runs.test.tsx`

**Interfaces:**
- Produces: `PanelSection({ id, title, summary, open, onToggle, problem, children })`: a header `<button aria-expanded aria-controls>` with the title and, when closed, the summary on the same line; `problem: boolean` shows the summary in the warning colour; content rendered only when open.
- Produces: `type PanelSectionId = "test_surfaces" | "mode" | "settings" | "carving"`; `DEFAULT_OPEN_SECTIONS: ReadonlySet<PanelSectionId> = new Set(["test_surfaces", "carving"])`; the open set lives in `CriteriaStep` state (kept when another criterion is selected) and the panel receives `openSections` and `onToggleSection`.
- Produces in `section_summaries.ts` (pure): `testSurfacesSummary(files: string[]) -> string` (one file: its name; two: "a.ply, b.ply"; more: "{n} files"; none: `messages.noTestSurfacesYet` "None yet"); `modeSummary(mode) -> string` (`plainModeName`); `criterionSettingsSummary(form) -> string` (modes with an analysis period: the period in the wording `step_summaries.ts` uses today, e.g. "21 Dec, 7 to 19 h"; other modes: "Starting values" when no criterion setting differs from the mode's starting values, else "{n} settings changed"); `carvingRuleSummary(form) -> string` (manual carve amount: "Carve {p} %"; a fixed cutoff: "Cutoff {v} {unit}"; automatic: "Automatic"; use `carvingRuleOf`, `manualCarveAmountOf` and `thresholdControlOf` from `CarvingStep.tsx`).
- Rules: a section with a problem opens when the problem appears (no test surfaces -> Test surfaces; a field error in the criterion form -> the section holding that field: Mode for `mode`, Carving rule for carving keys, Settings otherwise); "Go to <setting>" (run failure link, `goToSetting`) opens the holding section before focusing; the weather drop zone and the "values reset by mode change" notice belong to the Mode section and open it when they appear.

- [ ] **Step 1: Write the failing tests**: `section_summaries.test.ts` (each summary for its cases, exact strings above); `test the panel shows four sections with test surfaces and carving open`; `test a closed section shows its summary` ("Daylight", "21 Dec, 7 to 19 h", "Carve 70 %"); `test the open sections stay as the user left them when another criterion is selected`; `test go to a setting opens its section` (a refused run for `start_month` with Settings closed: after the link the section is open and the field focused); `test a criterion without test surfaces opens its test surfaces section` (summary "None yet" in the warning style).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): a criterion's panel in folded sections with one-line summaries`.

---

### Task 3: Add criterion from a short menu

**Files:**
- Create: `app/src/criteria/ModeMenu.tsx` (+ test)
- Modify: `app/src/criteria/CriterionList.tsx` (`AddCriterion`), `app/src/messages.ts`, `app/src/steps/steps.css`
- Test: `app/src/criteria/CriterionList.test.tsx`, `ProjectWorkspace.criterion_cards.test.tsx`

**Interfaces:**
- Produces: `ModeMenu({ onChoose, onClose, disabledReason })`: a `role="menu"` list under the Add criterion button, one `role="menuitem"` per entry of `MODE_TILES` in their order: `ModeTileSymbol`, `plain_name`, and `one_line` under it in the secondary style; arrow keys, Home, End, Escape (closes and refocuses the button) and Tab behave as in `ActionMenu`; the full tooltip text stays on the mode tiles in the panel's Mode section.
- `AddCriterion` opens `ModeMenu`; choosing calls `onAdd(mode)`; the new card is selected (as today) and its Test surfaces section is open (Task 2's rule for a criterion without files).

- [ ] **Step 1: Write the failing tests**: `test add criterion opens a menu of the modes` (six items in MODE_TILES order, names and one-liners), `test choosing a mode adds a selected criterion with its test surfaces open`, `test escape closes the menu and focuses add criterion`, `test the menu waits while a run is in progress` (items disabled with the run reason).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): add a criterion from a short menu of the modes`.

---

### Task 4: Run analysis and Build in the pinned bar

**Files:**
- Modify: `app/src/criteria/CriterionPanel.tsx` (no Run analysis), `app/src/steps/ProjectWorkspace.tsx` (`pinnedActions.criteria`), `app/src/steps/result_steps.tsx` (`pinnedAction`, the build button), `app/src/steps/steps.css`
- Test: `app/src/steps/ProjectWorkspace.saves_and_runs.test.tsx`, `ProjectWorkspace.criteria.test.tsx`, `app/src/steps/StepAccordion.test.tsx`

**Interfaces:**
- Produces: the Criteria step's pinned action is one bar: Run analysis (the `RunAnalysisButton` with its feedback, i.e. run progress, failure with its "Go to" link, refusals) and Build envelope and massing side by side; the build button is shown always in that bar and waits with its existing reasons (instead of appearing only when every criterion is carved). The panel no longer renders Run analysis. Site and grid's pinned Run analysis is unchanged.
- The pinned area keeps `max-height: 50%` with its own scroll (`.step-pinned-action`); long progress lists scroll inside it.

- [ ] **Step 1: Write the failing tests**: `test the criteria step pins run analysis and build`, `test the panel has no run analysis of its own`, `test the pinned run says what a criterion without test surfaces needs` ("Add test surfaces to {name}"), `test build waits in the pinned bar until every criterion is carved` (its existing reason), `test the pinned bar scrolls when the run progress is long` (the pinned element has the scrolling class and the step content stays rendered; style checked through the class, since jsdom has no layout).
- [ ] **Step 2: Run them to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test && npm run build`: PASS.
- [ ] **Step 5: Commit** `feat(app): run analysis and build pinned at the bottom of the criteria step`.

---

### Task 5: Docs and the merge tier

**Files:**
- Modify: `docs/ui.md` (the Criteria step: the list with one or more criteria, the On switch, sections, Add criterion menu, the pinned bar), `CHANGELOG.md` (under the unreleased "Added (chained carvings, app)" entry: one line for the reworked step)

- [ ] **Step 1: Write the docs.** `mkdocs build --strict -d <scratch>`: no warnings.
- [ ] **Step 2: Browser check** (controller): a copy of `~/UrbanSolarCarver/projects/New building among neighbors` and of `Allatini`: one criterion shows its row and the pinned Run analysis without scrolling past the carving rule; add a second criterion from the menu; switch one off and on; fold and unfold sections; a refused run's Go to link opens the right section; build and export.
- [ ] **Step 3: Run the merge tier once**: `python -m pytest -n 8`; in `app/`, `npm test && npm run build`.
- [ ] **Step 4: Commit** `docs: the reworked criteria step`.

---

## Not in this plan

- Renaming `bypassed` in the service or the data model (the UI inverts it).
- A "before / after" comparison readout for switching a criterion off (later, if comparing that way proves common).
- A per-row run button (ruled out by the user).
