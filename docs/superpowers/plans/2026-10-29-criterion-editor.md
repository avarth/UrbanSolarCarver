# Criterion editor and typical building window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Criteria step shows either the list of criteria or one criterion's settings under a sticky header, Carving
rule is the only section open by default, and the typical building opens as a modal window with values and chart side by side.

**Architecture:** `CriteriaStep` gains a `shows: "list" | "editor"` state owned by `ProjectWorkspace` (kept in
`WorkspaceSteps` so it survives a project rename); a new `CriterionEditorHeader` sits above today's `CriterionPanel` in the
editor. Everything that leads to one criterion's setting switches `shows` to `"editor"`. `TypicalBuildingSheet` keeps its
content and moves into a wide variant of `DialogFrame` with two columns.

**Tech Stack:** React 19 + TypeScript, Vite, Vitest + jsdom (`app/`), CSS tokens in `app/src/theme/tokens.css`.

**Spec:** `docs/superpowers/specs/2026-10-29-criterion-editor-design.md` (commit `45a2154`). Read it before Task 1.

## Global Constraints

- Work in a worktree on branch `feature/criterion-editor` from `main`; in a worktree run Python as
  `PYTHONPATH=src "D:/RESEARCH_CENTER/ACTIVE_PROJECTS/RSBenvelope_generation/urbanSolarCarver/.venv/Scripts/python.exe" -m pytest ...`
  and link `app/node_modules` to the main checkout's (`mklink /J`); remove the link before removing the worktree.
- The step panel stays 340 px wide. No engine or service change; the API is unchanged.
- Every colour from the tokens; check both themes (`body[data-theme="dark"]`).
- Labels in `app/src/messages.ts`, plain words, no em dashes, no developer words. New messages: `allCriteria: "All criteria"`,
  `criterionPosition: (position: number, count: number) => \`${position} of ${count}\``, `previousCriterion: "Previous criterion"`,
  `nextCriterion: "Next criterion"`, `done: "Done"`.
- Test tiers (CLAUDE.md): while editing `npx vitest run <file>` in `app/`; after each task `npm test && npm run typecheck`;
  before each commit of the last task `npm test && npm run build`, then the Python commit tier `-m "not sweep" -n 8`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never a bare `git stash`. No push.
- Code style: match the files' comment density and naming (header comment per file saying what it is, JSDoc per prop).

## Review Focus

1. Delete from the editor's menu of the selected criterion: the step returns to the list and the focus goes to the card selected
   then (not lost to `<body>`). Test in Task 1.
2. Previous or next while the new criterion's settings are still being read (`load.state === "loading"`): the header already
   names the new criterion and the sections area says it is loading; a refusal is said there. Test in Task 1.
3. A project renamed while a criterion's editor is open comes back on the same criterion, in the editor. Test in Task 2.
4. Escape in a library dialog (Save as new, Rename, Delete) over the typical building window closes only that dialog. Test in Task 4.
5. A criterion name of 80 characters wraps to at most two lines on the card and in the header, with the full name as the
   accessible name. Test in Task 3.

---

### Task 1: List or editor in the Criteria step, with the editor's header

**Files:**
- Create: `app/src/criteria/CriterionEditorHeader.tsx`
- Modify: `app/src/criteria/CriteriaStep.tsx` (props and render), `app/src/criteria/CriterionList.tsx` (export its rename/delete
  dialog handling for reuse, see Step 3), `app/src/messages.ts`, `app/src/steps/steps.css`
- Test: `app/src/criteria/CriteriaStep.test.tsx`, create `app/src/criteria/CriterionEditorHeader.test.tsx`

**Interfaces:**
- Produces:
  - `export type CriteriaShows = "list" | "editor";` in `CriteriaStep.tsx`.
  - `CriteriaStepProps` gains `shows: CriteriaShows; onShowsChange: (shows: CriteriaShows) => void;` (both required).
  - `CriterionEditorHeader({ entry, line, position, count, onShowList, onPrevious, onNext, disabledReason, deleteDisabledReason, onSetBypassed, onChoose }: CriterionEditorHeaderProps)`
    with `entry: CriterionEntry; line: string; position: number /* 1-based */; count: number; onShowList: () => void;
    onPrevious: () => void; onNext: () => void; disabledReason: string | null; deleteDisabledReason: string | null;
    onSetBypassed: (on: boolean) => void; onChoose: (item: CriterionMenuItem) => void`.
  - `CriterionList` exports `useCriterionDialogs(props: Pick<CriterionListProps, "onRename" | "onDelete">): { open: (kind: "rename" | "delete", criterion: CriterionEntry) => void; dialogs: ReactNode }`,
    used by the list and by the header's menu.

- [ ] **Step 1: Write the failing tests in `CriteriaStep.test.tsx`**

Replace the three tests that expect the panel under the cards ("one criterion shows its row…", "two criteria show their
cards…", "the chain summary line comes under the cards, before the panel…") with:

```tsx
test("the list view shows the cards, Add criterion and the chain line, and no panel", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={() => {}} chainLine="Kept 188 073 m³, 19 % of the maximum volume"
                                         list={listProps([entry("1", "Daylight on windows"), entry("2", "Solar energy on roofs")])} />);
  expect(rendered.container.querySelectorAll(".criterion-card")).toHaveLength(2);
  expect(rendered.container.querySelector(".chain-summary")!.textContent).toBe("Kept 188 073 m³, 19 % of the maximum volume");
  expect(rendered.container.querySelector(".criterion-panel-frame")).toBeNull();
  expect(rendered.container.querySelector(".criterion-editor-header")).toBeNull();
});

test("a press on a card selects it and asks for the editor", () => {
  const onSelect = vi.fn(), onShowsChange = vi.fn();
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="list" onShowsChange={onShowsChange}
                                         list={listProps([entry("1", "Daylight on windows"), entry("2", "Solar energy on roofs")], { onSelect })} />);
  click(rendered.container.querySelectorAll<HTMLButtonElement>(".criterion-card-select")[1]);
  expect(onSelect).toHaveBeenCalledWith("2");
  expect(onShowsChange).toHaveBeenCalledWith("editor");
});

test("the editor view shows the header and the panel, not the cards; the focus goes to the criterion's name", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}}
                                         list={listProps([entry("1", "Daylight on windows"), entry("2", "Solar energy on roofs")], { selectedId: "2" })} />);
  expect(rendered.container.querySelector(".criterion-card")).toBeNull();
  expect(rendered.container.querySelector(".criterion-editor-name")!.textContent).toBe("Solar energy on roofs");
  expect(rendered.container.querySelector(".criterion-editor-position")!.textContent).toBe("2 of 2");
  expect(rendered.container.querySelector(".criterion-panel-frame")).not.toBeNull();
  expect(document.activeElement).toBe(rendered.container.querySelector(".criterion-editor-name"));
});

test("All criteria asks for the list; previous and next select the neighbours in carving order", () => {
  const onSelect = vi.fn(), onShowsChange = vi.fn();
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={onShowsChange}
                                         list={listProps([entry("1", "A"), entry("2", "B"), entry("3", "C")], { selectedId: "2", onSelect })} />);
  click(buttonNamed("Previous criterion"));
  expect(onSelect).toHaveBeenLastCalledWith("1");
  click(buttonNamed("Next criterion"));
  expect(onSelect).toHaveBeenLastCalledWith("3");
  click(buttonNamed("All criteria"));
  expect(onShowsChange).toHaveBeenLastCalledWith("list");
});

test("with one criterion the header has no position and no previous or next", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}} list={listProps([entry("1", "A")])} />);
  expect(rendered.container.querySelector(".criterion-editor-position")).toBeNull();
  expect(buttonNamed("Previous criterion")).toBeUndefined();
});

test("Add criterion and Duplicate open the new criterion's editor; Delete returns to the list with the focus on the card selected", async () => { /* see Step 1 note */ });

test("after previous or next, while the criterion's settings are read, the header names it and the sections say they wait", () => {
  rendered = renderForTest(<CriteriaStep panel={PANEL} shows="editor" onShowsChange={() => {}} load={{ state: "loading" }}
                                         list={listProps([entry("1", "A"), entry("2", "B")], { selectedId: "2" })} />);
  expect(rendered.container.querySelector(".criterion-editor-name")!.textContent).toBe("B");
  expect(rendered.container.querySelector(".criterion-panel-waits")!.getAttribute("role")).toBe("status");
});
```

Step 1 note for the Add/Duplicate/Delete test: with `onAdd`, `onDuplicate`, `onDelete` resolving `null`, assert
`onShowsChange` was called with `"editor"` after Add and Duplicate, and with `"list"` after Delete; after Delete, rerender with
`shows="list"` and the next criterion selected and assert `document.activeElement` is that card's `.criterion-card-select`
(Review Focus 1). The file's `buttonNamed` matches `textContent` only: extend it to match `aria-label` too, for the icon
buttons, and keep its `!` uses working.

In `CriterionEditorHeader.test.tsx`: the switch's `aria-label` is `messages.criterionSwitchLabel(name)` and turning it calls
`onSetBypassed(true)`; the menu offers Rename, Duplicate and Delete with Delete's `disabledReason` from `deleteDisabledReason`;
the result line has `title` equal to the whole line.

- [ ] **Step 2: Run them and see them fail**

Run: `npx vitest run src/criteria/CriteriaStep.test.tsx src/criteria/CriterionEditorHeader.test.tsx` (in `app/`)
Expected: FAIL (`shows` is not a prop; no `.criterion-editor-header`).

- [ ] **Step 3: Implement**

- `CriterionEditorHeader.tsx`: three rows inside `<div className="criterion-editor-header">` (row 1: `All criteria` button
  with a back chevron, then at the right `<span className="criterion-editor-position">` and two icon buttons named
  `messages.previousCriterion` / `messages.nextCriterion`, only when `count > 1`, disabled at the ends; row 2: swatch, name in
  `<h3 className="criterion-editor-name" tabIndex={-1}>`, mode symbol (`ModeTileSymbol`, as in `CriterionCard`), the switch and
  the `ActionMenu`, both as on the card; row 3: `<p className="criterion-editor-line" title={line}>`).
- Move the rename/delete dialog state of `CriterionList` into `useCriterionDialogs` and use it from both; the header's menu
  calls `open("rename" | "delete", entry)`, Duplicate calls `list.onDuplicate`.
- `CriteriaStep`: in `"list"` render `CriterionList` (its `onSelect` wrapped to also call `onShowsChange("editor")`) and the
  chain line; in `"editor"` render the header for the selected entry (line from `list.lineOf`) and the existing `panelFrame`.
  Add and Duplicate resolving `null` call `onShowsChange("editor")`; Delete resolving `null` calls `onShowsChange("list")`
  and keeps today's focus request (the card selected then). On entering `"editor"` (and on each new `selectedId` while in it)
  focus `.criterion-editor-name`.
- CSS in `steps.css`: `.criterion-editor-header { position: sticky; top: 0; z-index: 2; background: var(--colour-panel); }`
  with a bottom line `var(--colour-line)`; total height about 90 px (row gaps `var(--space-unit)`); name clamped to two lines
  (`display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden`); the line one line with
  ellipsis. Remove `.criteria-list-block + .criterion-panel-frame` and `.chain-summary + .criterion-panel-frame` rules.

- [ ] **Step 4: Run them and see them pass**

Run: `npx vitest run src/criteria` then `npm run typecheck`
Expected: PASS. `ProjectWorkspace` does not compile yet because `shows` is required: pass `shows="editor"` and
`onShowsChange={() => {}}` there for now (Task 2 replaces it), so `npm test` stays green.

- [ ] **Step 5: Commit**

```bash
git add app/src/criteria app/src/messages.ts app/src/steps/steps.css app/src/steps/ProjectWorkspace.tsx
git commit -m "feat(app): the Criteria step shows the list or one criterion under its own header"
```

### Task 2: The workspace decides list or editor, and every way to a criterion's setting opens the editor

**Files:**
- Modify: `app/src/steps/ProjectWorkspace.tsx` (`WorkspaceSteps`, state, the `criteria` entry of `stepContent`),
  `app/src/criteria/use_criterion_selection.ts` (source gains `onShowCriterion`), `app/src/criteria/use_workspace_criteria.ts`
  (passes it through), `app/src/criteria/use_criteria.ts` (`useCriteria(token, project, startSelectedId?)`), `app/src/App.tsx` only
  if `WorkspaceSteps` handling needs it (it stores the object as it is)
- Create: `app/src/criteria/criteria_shows.ts`
- Test: create `app/src/criteria/criteria_shows.test.ts`; `app/src/steps/ProjectWorkspace.criteria.test.tsx`

**Interfaces:**
- Consumes: `CriteriaShows`, `shows`, `onShowsChange` from Task 1.
- Produces:
  - `WorkspaceSteps` gains `criteria?: { shows: CriteriaShows; criterionId: string }`.
  - `export function firstCriteriaShows(criterionCount: number): CriteriaShows` in `criteria_shows.ts`: `"editor"` for 1,
    `"list"` otherwise (0 included).
  - `CriterionSelectionSource` gains `onShowCriterion?: () => void`, called whenever `showCriterion` selects a criterion
    (refusals, `goToSetting`), before its settings are read.
  - `useCriteria(token: string, project: ProjectDetail, startSelectedId?: string): CriteriaHook`: starts on that id when the
    project lists it, else on the first.

- [ ] **Step 1: Write the failing tests**

`criteria_shows.test.ts`:
```ts
test("the step opens on the editor for one criterion, on the list otherwise", () => {
  expect(firstCriteriaShows(1)).toBe("editor");
  expect(firstCriteriaShows(2)).toBe("list");
  expect(firstCriteriaShows(0)).toBe("list");
});
```

In `ProjectWorkspace.criteria.test.tsx` (use its existing fake service and helpers), one test each:
- "a project with one criterion opens the Criteria step on its editor; with two, on the list".
- "after All criteria, closing and opening the Criteria step shows the list again" (remembered, not recomputed).
- "a run that ends and opens the Criteria step keeps the list or the editor as it was".
- "a run refused because a criterion has no test surfaces opens that criterion's editor, from Site and grid and from the
  Criteria bar" (two runs: origins `settings_run_analysis` and `carving_run_analysis`; the bar's reason is still under its button).
- "a run failure's link to a criterion setting opens the editor of that criterion with the field focused".
- "a new weather file's notice opens the Criteria step on the criterion it concerns, its notice under the Settings header".
- "deleting criteria down to one leaves the step on the list".
- "the workspace made again after a rename opens on the same criterion, in the editor" (render with
  `startSteps={{ open: "criteria", view: "criteria", criteria: { shows: "editor", criterionId: "2" } }}`; assert
  `.criterion-editor-name` is criterion 2's name; Review Focus 3). Also assert `onStepsChange` is called with `criteria`.

- [ ] **Step 2: Run them and see them fail**

Run: `npx vitest run src/criteria/criteria_shows.test.ts src/steps/ProjectWorkspace.criteria.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

- `ProjectWorkspace`: `const [criteriaShows, setCriteriaShows] = useState<CriteriaShows | null>(props.startSteps?.criteria?.shows ?? null)`;
  when `openStep === "criteria"` and it is `null`, set it to `firstCriteriaShows(criteria.criteria.length)` (a layout effect,
  so the first paint is right). Pass `shows={criteriaShows ?? firstCriteriaShows(criteria.criteria.length)}` and
  `onShowsChange={setCriteriaShows}`.
- Set `"editor"` when: `settingToFocus` becomes non-null for a setting whose `stepOfSetting(...)` is `"criteria"`; the selection
  source's `onShowCriterion` fires; `weatherChangeSuggestionNow` goes from null to non-null (it belongs to the selected
  criterion's form, which is the one the editor shows).
- `onStepsChange` reports `criteria: { shows, criterionId: shownCriterionId }` once `criteriaShows` is set.
- `useCriteria(token, project, props.startSteps?.criteria?.criterionId)`.

- [ ] **Step 4: Run them and see them pass**

Run: `npx vitest run src/steps src/criteria` then `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src
git commit -m "feat(app): the workspace opens a criterion's editor for one criterion and for every way to its settings"
```

### Task 3: Cards that show whole names, and Carving rule alone open by default

**Files:**
- Modify: `app/src/criteria/CriterionCard.tsx`, `app/src/criteria/section_summaries.ts:18`, `app/src/steps/steps.css`
  (`.criterion-card*`, `.panel-section-summary`)
- Test: `app/src/criteria/CriterionCard.test.tsx` (also the CSS check), `app/src/criteria/CriterionPanel.test.tsx`

**Interfaces:**
- Produces: `DEFAULT_OPEN_SECTIONS` becomes `new Set(["carving"])`.

- [ ] **Step 1: Write the failing tests**

```tsx
test("a card shows its whole name on up to two lines, its line under it, and a chevron that says it opens", () => {
  const name = "Solar usefulness on alatini_testSrfs_solargains_with_a_long_tail_of_eighty_characters_x";
  renderCard({ entry: { ...DAYLIGHT, name } });       // the file's helpers
  expect(rendered.container.querySelector(".criterion-card-name")!.textContent).toBe(name);
  expect(rendered.container.querySelector(".criterion-card-chevron")!.getAttribute("aria-hidden")).toBe("true");
  const css = readFileSync("src/steps/steps.css", "utf8");
  expect(css).toMatch(/\.criterion-card-name\s*{[^}]*-webkit-line-clamp:\s*2/);
  expect(css).not.toMatch(/\.criterion-card-name\s*{[^}]*white-space:\s*nowrap/);
});
```
In `CriterionPanel.test.tsx`: "a criterion opens with only Carving rule open; a criterion without test surfaces opens Test
surfaces as well" (render through `usePanelSections(null)` as the file's other tests do).
Update the existing tests that expect Test surfaces open by default.

- [ ] **Step 2: Run them and see them fail**

Run: `npx vitest run src/criteria/CriterionCard.test.tsx src/criteria/CriterionPanel.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Card markup: the select button holds swatch, text and symbol as today, plus `<span className="criterion-card-chevron" aria-hidden="true">›</span>`
at its end; CSS lays the card out as a grid so the line spans the card's width under name, symbol, switch and menu (the
line is a sibling row, not squeezed beside them). Name: two-line clamp as in Task 1. Closed section summaries:
`white-space: nowrap; overflow: hidden; text-overflow: ellipsis`. `DEFAULT_OPEN_SECTIONS = new Set(["carving"])`.

- [ ] **Step 4: Run them and see them pass**

Run: `npx vitest run src/criteria` then `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src
git commit -m "feat(app): criterion cards show whole names; only Carving rule opens by default"
```

### Task 4: The typical building window

**Files:**
- Modify: `app/src/steps/ProjectDialogs.tsx` (`DialogFrame`), `app/src/criteria/TypicalBuildingSheet.tsx` (its three returns),
  `app/src/criteria/CriterionPanel.tsx` (comment only: "opens its window"), `app/src/steps/steps.css` (remove
  `.typical-building-sheet` positioning at 643-660 and the narrow-window rules at 738-740; add the window's columns)
- Test: `app/src/criteria/TypicalBuildingSheet.test.tsx` (there is no `ProjectDialogs.test.tsx`; the project dialogs' own
  tests in `steps/ProjectMenu.test.tsx` must stay green, which proves the `DialogFrame` defaults unchanged)

**Interfaces:**
- Produces: `DialogFrameProps` gains `wide?: boolean` (class `project-dialog project-dialog-wide`), `closeLabel?: string`
  (an × button in the title row that calls `onClose`), and `titleTakesFocus?: boolean` (the `h2` gets `tabIndex={-1}` and
  takes the focus on open instead of the first control). Defaults keep today's dialogs unchanged.
- `TypicalBuildingSheet` keeps its props (`id`, `building`, `includesHarm`, `hasWeatherFile`, `disabledReason`, `onClose`).

- [ ] **Step 1: Write the failing tests** in `TypicalBuildingSheet.test.tsx`

- "the typical building opens as a modal window: aria-modal, its title takes the focus, × and Done close it" (assert
  `[role="dialog"][aria-modal="true"]`, `.project-dialog-wide`, `document.activeElement` is the `h2` "Typical building",
  `closed` increments on × and on Done).
- "Escape closes the window; in a library dialog over it, Escape closes only that dialog" (open Save as new, dispatch
  Escape on its field, assert the library dialog is gone and the window is still there; Review Focus 4).
- "Tab stays inside the window".
- "the values are in the left column and Calculate, the chart and the numbers in the right one"
  (`.typical-building-window-values` holds `.typical-building-groups`; `.typical-building-window-results` holds
  `.typical-building-calculate` and `.weights-chart`).
- CSS: `steps.css` has `@media (min-width: 900px)` with `.typical-building-window-columns { display: grid; grid-template-columns: minmax(0, 440px) minmax(0, 1fr)`
  and `.project-dialog-wide { width: min(880px, 100%)`; no `.typical-building-sheet {` rule with `position: fixed`.
Update the existing tests that query `.typical-building-sheet` or expect focus on the × button.

- [ ] **Step 2: Run them and see them fail**

Run: `npx vitest run src/criteria/TypicalBuildingSheet.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Wrap each of the sheet's three returns in `<DialogFrame title={messages.typicalBuilding} busy={false} onClose={onClose} wide closeLabel={messages.closeTypicalBuilding} titleTakesFocus>`;
drop the sheet's own header and `closeOnEscape` (the frame does both). In the full return put Library and its buttons, the
groups and Advanced in `.typical-building-window-values`, and Calculate and the results in `.typical-building-window-results`,
inside `.typical-building-window-columns`; end with `<div className="project-dialog-buttons"><button type="button" className="primary-button" onClick={onClose}>{messages.done}</button></div>`.
The two short returns (reading, no building chosen) stay one column. Window height `max-height: calc(100vh - 64px)`; at 900 px
and wider the values column scrolls (`overflow-y: auto`) and the results column does not move; under 900 px one column, the
window scrolls. The chart canvas height 140 px in the window. Focus returns to Edit building on close (already done by
`CriterionPanel.closeSheet`).

- [ ] **Step 4: Run them and see them pass**

Run: `npx vitest run src/criteria src/steps` then `npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src
git commit -m "feat(app): the typical building opens as a modal window, values beside the chart"
```

### Task 5: Docs, build, and a check on Allatini

**Files:**
- Modify: `docs/ui.md` ("Several criteria" and its subsections "The list", "The panel of a criterion", "The pinned bar"; "The
  typical building"), `CHANGELOG.md` (`[Unreleased]`, a "Changed (app: criterion editor)" entry), `src/urbansolarcarver/ui_static/*` (build)

- [ ] **Step 1: Rewrite the docs** to describe the list view, the editor and its header, the default sections, and the window.

- [ ] **Step 2: Build and run the commit tiers**

Run in `app/`: `npm test && npm run build`; then the Python commit tier
`PYTHONPATH=src ".../.venv/Scripts/python.exe" -m pytest -m "not sweep" -n 8`
Expected: all pass (`tests/test_local_web_packaging.py` included).

- [ ] **Step 3: Check in the browser** on a copy of Allatini in a scratch projects folder (never
  `C:/Users/arisv/UrbanSolarCarver/projects`), with a launch config like `usc-ui-theme` (scratch projects folder and fake home).
  In the light and dark themes, with screenshots: the list; the Solar usefulness editor after a run, where the top of Carving
  rule is within 200 px of the top of the editor (measure with `getBoundingClientRect`); previous and next; the typical
  building window at 1440 x 900 and at 800 x 600.

- [ ] **Step 4: Commit**

```bash
git add docs/ui.md CHANGELOG.md src/urbansolarcarver/ui_static
git commit -m "docs: the criterion editor and the typical building window; rebuild ui_static"
```
