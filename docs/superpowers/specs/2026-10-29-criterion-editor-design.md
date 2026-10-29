# Criterion editor and typical building window: design

Date: 2026-10-29. Status: draft for the user's review.
Source: the UI review of 2026-10-29 (vault `ui-ux/ui-review-2026-10-29.md`, items 1 to 3) and the user's choices after it:
layout A ("open a criterion in the panel"), and the typical building as a window over the app.

## Why

The Criteria step holds two jobs in one scrolling column: the list of criteria and every setting of the selected one. On a
copy of Allatini (three criteria, 619 px of panel height) the step is 1,527 px tall with the default sections open and
2,732 px with all of them open, 67 controls in one step. Once the cards scroll away, nothing says which criterion is being
edited. The carve amount and the histogram, the controls changed most after a run, sit near the bottom.

Solar usefulness with Energy-weighted adds a third column: the typical building's sheet opens beside the panel, 360 px wide,
over the 3D view. Its day-by-hour chart squeezes 365 days into about 300 px.

## Goals

- The Criteria step shows either the list of criteria or one criterion's settings (the editor), never both stacked.
- The editor's name stays in view while its sections scroll.
- After a run, the carving rule of an opened criterion starts within about 200 px of the top of the editor, header included
  (the test: Allatini's Solar usefulness criterion, 340 px panel, default sections).
- The typical building is edited in a modal window in the middle of the screen, wide enough for the values and the chart side
  by side.

## Non-goals

- The numbers of a criterion (review item 5: kept 49 % here and 19 % there, "score carved" and "obstruction removed"). Only
  where the chain's line sits changes.
- Simulate, Inspect, the sky dome, the framing of the 3D view (review items 8 to 12).
- New settings, or a change to what any setting does. No engine or service change; the API stays as it is.
- A movable or non-modal window: the user does not need the 3D view or the panel while editing the typical building.

## Anti-goals

- Anything that makes a project with one criterion take more clicks than today to reach its settings.
- Sections jumping to another place when a run ends.
- The panel growing wider than 340 px, or a third column over the 3D view.

## Constraints

- The step panel stays 340 px wide; the other steps (Inputs, Site and grid, Envelope and massing, Export) and the pinned bar
  (Run analysis, Build envelope and massing) are unchanged.
- Every colour from the tokens, in both themes (light and dark, `theme/app_theme.tsx`).
- Plain labels in `messages.ts`, no developer words (vault `ui-ux/backlog.md`, standing preferences).
- The run, the selection and the save rules of today stay: selecting a criterion saves a change still waiting to the one left
  (`use_criterion_selection.ts`); a run refused for a criterion shows that criterion with its fields marked.
- Tests updated to the new layout; `docs/ui.md` ("Several criteria", "The typical building") rewritten to match; `ui_static`
  rebuilt.

## The list view

What the Criteria step shows when no criterion is opened.

- The cards in carving order, as today: drag handle (two or more criteria), colour dot, name, mode symbol, the on/off switch,
  the menu (Rename, Duplicate, Delete), and the result or status line.
- The name wraps to two lines instead of being cut with an ellipsis; the result line runs under it at the card's full width,
  not squeezed beside the switch and the menu. (Today: "Daylight on al…", and the result wraps to three lines.)
- A chevron at the right end of each card says it opens. A press on the card, or Enter or Space on it, opens its editor. The
  drag handle, the switch and the menu keep their own actions and do not open it.
- Under the cards: Add criterion, then, with two or more criteria, the chain's line ("Kept 188 073 m³, 19 % of the maximum
  volume"), as today.
- The card of the criterion opened last stays marked as selected, and the 3D view keeps showing its layers, as the selected
  criterion does today.

## The editor view

What the Criteria step shows when a criterion is opened. It takes the place of the list inside the step; the step stays open.

### Header

At the top of the editor, sticking to the top of the step list's scroll area while the sections scroll under it. Three rows,
about 90 px in all, so the 200 px goal holds:

- Row 1: "All criteria", a button with a back chevron, at the left: returns to the list, with the focus on this criterion's
  card. At the right, with two or more criteria: "1 of 3" and previous and next buttons, which open the criterion before or
  after in carving order (the same save rule as selecting a card).
- Row 2: the criterion's colour dot, its name (up to two lines), its mode symbol, the on/off switch and the menu (the same
  actions as on the card; Delete from here returns to the list).
- Row 3: its result or status line, on one line, cut with an ellipsis when it is longer; the whole line on hover and for screen
  readers.

The closed sections' summaries stay on one line, cut the same way.

### Sections

The four sections of today, in today's order: Test surfaces, Mode, Settings, Carving rule. Each closed section is one line
with its summary (Mode shows "Solar usefulness"; opening it shows the tiles, which is how the mode is changed).

Which are open by default changes: only Carving rule (today: Test surfaces and Carving rule). The rule that opens a section
when it has something to fix stays (no test surfaces, a weather file missing, a field with an error, values reset by a mode
change), so a new criterion still opens Test surfaces by itself. The sections the user opens or closes still belong to the
workspace, as today, and hold when another criterion is opened.

With the list gone from above, a header of about 90 px and three closed sections of about 40 px each, the carving rule starts
about 210 px from the top of the editor; trimming the header's padding brings it under 200 px. Before the first run it says
"Run the analysis to see the carving", as today.

### Moving in and out

- Opening a card, Add criterion and Duplicate open the editor of that criterion; the focus goes to its name in the header.
- "All criteria" and Delete return to the list.
- Anything that leads to one criterion's setting opens that criterion's editor first, then its section and field, as the
  panel's links do today: a run refused for a criterion (from Site and grid or from the Criteria bar's Run analysis, wherever
  the step was), a run failure's link to a setting (`goToSetting`, `focusSetting`), the weather notice. A refusal from the
  Criteria bar is still said under its button as well.
- The notice of a new weather file belongs to the criterion it offers a new period to: while it waits, opening the Criteria
  step opens that criterion's editor, where the notice shows under the Settings header as today.
- The first time the Criteria step opens after the project opens, a project with one criterion opens on its editor; with two
  or more, on the list. From then on the step remembers whether it showed the list or the editor, and which criterion, while
  the project stays open (also across a rename of the project, through the workspace's open steps), including when a run ends
  and opens the step. Deleting criteria down to one does not open the editor by itself.

## The typical building window

Replaces the sheet beside the panel (`TypicalBuildingSheet`). It opens from Edit building in the Settings section (Solar
usefulness, Energy-weighted); the box there (name, state, Edit building) stays as it is.

- A modal window in the middle of the screen over a dimmed app (the dialog scrim and shadow tokens), like the project dialogs
  (`ProjectDialogs.tsx`: `role="dialog"`, `aria-modal="true"`). The focus moves to its title and stays inside it; on closing it
  returns to Edit building.
- Closes with ×, Escape, or Done at the bottom right. There is no Cancel: the values save as they are typed, as today.
- Width up to 880 px (never more than the window less 32 px); height up to the window less 64 px.
- At 900 px of window width or more, two columns: on the left (about 440 px) Library, Use, Fabric, Summer shading and Advanced,
  scrolling on their own; on the right Calculate, the chart and the results (Heating, Cooling, Hours that count), which stay in
  view while the left column scrolls. The chart is drawn at the right column's width. Under 900 px, one column in today's order.
- The library's own dialogs (Save as new, Rename, Delete) open over the window.
- While a run is under way the window says why its values wait, as the sheet does today.

## Left to the builder

- How the components are split (for example a `CriterionEditor` holding the header and today's `CriterionPanel`), and where the
  list-or-editor state lives (next to the workspace's open steps is the expected place).
- The sticky header's CSS, the chevron and back icons, the exact spacing.
- The words of the new labels ("All criteria", "1 of 3", the previous and next buttons' names), in `messages.ts`, plain.
- The test split.

## Calls made by Claude (to check while reading)

1. Carving rule comes near the top by changing which sections are open by default, not by moving it above the others. Moving it
   only once a result exists would make it jump when a run ends.
2. A project with one criterion opens straight on its editor (anti-goal: no extra click for one criterion).
3. The on/off switch and the menu are in the editor's header as well as on the card.
4. Previous and next buttons in the header, to move between criteria without going back to the list.
5. Card names wrap to two lines instead of being cut.
6. The typical building window has Done and no Cancel, since values already save as typed.
7. In the list view the 3D view keeps showing the criterion opened last.
8. The editor's header is three rows of about 90 px, its result line on one line cut with an ellipsis (whole on hover), so the
   carving rule starts within about 200 px.
9. Every link to one criterion's setting (refused runs from anywhere, run failure links, the weather notice) opens that
   criterion's editor first.
10. "One criterion opens on its editor" applies only the first time the step opens after the project opens; after that the
    step remembers list or editor.
