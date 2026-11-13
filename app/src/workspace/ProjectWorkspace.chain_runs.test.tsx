// The runs and saves of a project with several criteria (spec 7.3), against a fake service of a chain: progress per criterion and on
// the cards, refusals at their card, the carving lock per criterion and the live rethreshold from an earlier criterion.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ProjectDetail } from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { packScorePoints } from "../viewer/packed_results_for_test";
import {
  CURRENT, FACADES, OUT_OF_DATE, ROOFS, WINDOWS, card, cardLine, carvingSummaryOf, openChain, panel, panelFrame, select, selectedCardName,
  service as chainService,
  type CriterionStages,
} from "./chain_service_for_test";
import {
  buildPart, buttonIn, container, endWorkspaceTest, openStep, closeProjectSettings, projectSettings, settingsButton, panelSectionOpen, pinnedBar, pressRunAnalysis, reasonOf, settle, showCriterionCards,
  showCriterionEditor, startWorkspaceTest, switchMode, thresholdField, thresholdOf, togglePanelSection, typeAndLeave, voxelSizeField, waitForTheSave,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const THRESHOLD_OUT_OF_DATE: CriterionStages = { preprocessing: "current", thresholding: "out_of_date" };
const NOT_RUN: CriterionStages = { preprocessing: "missing", thresholding: "missing" };
/** The stages of the run shown in the criterion's panel: each one's name and state. */
const stageRows = () => [...pinnedBar().querySelectorAll(".run-stage")]
  .map((row) => `${row.querySelector(".run-stage-name")!.textContent} | ${row.querySelector(".run-stage-state")!.textContent}`);
/** A card's result line of a mode that is not weighted, as formatNumber writes it (no-break spaces before the units). */
const volumeLine = (percent: number) => `Removes ${percent} % of what reached it`;
/** How often *text* is on the page in *root*. */
const timesShown = (root: Element, text: string) => (root.textContent ?? "").split(text).length - 1;
const editorName = () => container().querySelector(".criterion-editor-name")?.textContent ?? null;

async function bypass(name: string) {
  await act(async () => card(name).querySelector<HTMLInputElement>('[role="switch"]')!.click());
  await settle();
}

test("a run of two criteria shows each one's stages by name; its card says Running, and a later one updates from it until its thresholding finishes", async () => {
  await openChain([FACADES, WINDOWS], { 1: OUT_OF_DATE, 2: THRESHOLD_OUT_OF_DATE });
  expect(cardLine("Winter sun on facades")).toBe("Out of date");
  expect(cardLine("Spring sun on windows")).toBe("Updates from Winter sun on facades");
  chainService.runCriterionStages = { 1: ["preprocessing", "thresholding"], 2: ["thresholding"] };
  await pressRunAnalysis();
  expect(chainService.runsStarted).toEqual([["thresholding"]]);
  expect(stageRows()).toEqual([
    "Winter sun on facades: Sun analysis | running", "Winter sun on facades: Carving | waiting", "Spring sun on windows: Carving | waiting",
  ]);
  expect(cardLine("Winter sun on facades")).toBe("Running");
  expect(card("Winter sun on facades").getAttribute("aria-busy")).toBe("true");
  expect(cardLine("Spring sun on windows")).toBe("Updates from Winter sun on facades");

  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "preprocessing", criterion: "1", done: 2, total: 4 });
  expect(stageRows()[0]).toBe("Winter sun on facades: Sun analysis | 2 of 4 batches");
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "1", done: 0, total: 1 });
  expect(cardLine("Winter sun on facades")).toBe("Running");
  expect(cardLine("Spring sun on windows")).toBe("Updates from Winter sun on facades");
  chainService.summaryCriteria = [carvingSummaryOf(FACADES, 70), carvingSummaryOf(WINDOWS, 80)];      // criterion 1's new numbers
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "2", done: 0, total: 1 });
  expect(stageRows()).toEqual([
    "Winter sun on facades: Sun analysis | done", "Winter sun on facades: Carving | done", "Spring sun on windows: Carving | running",
  ]);
  expect(cardLine("Winter sun on facades")).toBe("Running");          // its new numbers are on their way, not the ones from before
  expect(card("Winter sun on facades").getAttribute("aria-busy")).toBeNull();
  await settle();
  expect(cardLine("Winter sun on facades")).toBe(volumeLine(30));
  expect(cardLine("Spring sun on windows")).toBe("Running");

  chainService.criterionStages = { 1: CURRENT, 2: CURRENT };
  chainService.summaryCriteria = [carvingSummaryOf(FACADES, 70), carvingSummaryOf(WINDOWS, 75)];
  run.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();
  expect(cardLine("Spring sun on windows")).toBe(volumeLine(25));
});

test("a card that waits for its numbers after a run stops saying Running when the summary cannot be read, even on the project's first run", async () => {
  await openChain([FACADES, WINDOWS], { 1: OUT_OF_DATE, 2: OUT_OF_DATE }, (service) => { service.summaryStatus = 404; });
  chainService.runCriterionStages = { 1: ["preprocessing", "thresholding"], 2: ["preprocessing", "thresholding"] };
  await pressRunAnalysis();
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "1", done: 0, total: 1 });
  run.send({ type: "stage_progress", stage: "preprocessing", criterion: "2", done: 0, total: 1 });
  await settle();
  expect(cardLine("Winter sun on facades")).not.toBe("Running");      // the summary was asked for again and answered 404: no numbers to wait for
  chainService.criterionStages = { 1: CURRENT, 2: CURRENT };
  run.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();
  expect(cardLine("Winter sun on facades")).not.toBe("Running");
  expect(cardLine("Spring sun on windows")).not.toBe("Running");
});

test("a carving update's failure is said in the pinned bar, whether the Carving rule section is open or closed", async () => {
  await openChain([FACADES], { 1: CURRENT });
  chainService.runRefusal = { status: 503, body: { detail: "The analysis service is busy." } };
  typeAndLeave(thresholdField(), "1");
  await waitForTheSave();
  await settle();
  expect(timesShown(pinnedBar(), "The analysis service is busy.")).toBe(1);
  expect(panel().querySelector(".run-outcome")).toBeNull();                       // not in the section
  togglePanelSection("Carving rule");
  expect(panelSectionOpen("Carving rule")).toBe(false);
  expect(timesShown(pinnedBar(), "The analysis service is busy.")).toBe(1);
});

test("with one criterion a run's stages keep their names, with no criterion's", async () => {
  await openChain([FACADES], { 1: OUT_OF_DATE });
  chainService.runCriterionStages = { 1: ["preprocessing", "thresholding"] };
  await pressRunAnalysis();
  expect(stageRows()).toEqual(["Sun analysis | running", "Carving | waiting"]);
});

test("a run refused for criterion 2's settings selects its card, says so in its panel and marks the field", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: OUT_OF_DATE });
  chainService.runRefusal = {
    status: 422, body: { field_errors: [{ field: "max_slope_deg", message: "Input should be less than 90" }], grid_plan: null, criterion: "2" },
  };
  await pressRunAnalysis();
  expect(chainService.requests).toContain("GET /criteria/2/settings");
  expect(pinnedBar().textContent).toContain("The run stopped on an error.");
  expect(container().querySelector('[data-setting="max_slope_deg"] .setting-error')!.textContent).toBe("Input should be less than 90");
  expect(selectedCardName()).toBe("Spring sun on windows");
  showCriterionEditor();
  await select("Winter sun on facades");
  expect(container().querySelector('[data-setting="max_slope_deg"] .setting-error')).toBeNull();      // criterion 1's settings are fine
});

test("a run refused for missing test surfaces selects that criterion and asks for them once, in the pinned bar", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: OUT_OF_DATE });
  // The service found criterion 2's test surfaces gone (removed in another tab, say).
  const refusal = "Choose test surfaces for Spring sun on windows.";
  chainService.runRefusal = { status: 422, body: { detail: refusal, missing_inputs: ["test_surfaces:2"] } };
  expect(editorName()).toBeNull();                                // two criteria: the step opens on the list
  await pressRunAnalysis();                                       // the pinned Run analysis, which says the refusal itself
  expect(editorName()).toBe("Spring sun on windows");
  expect(pinnedBar().querySelector(".run-outcome-error")!.textContent).toBe(refusal);
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(timesShown(pinnedBar(), refusal)).toBe(1);
  expect(timesShown(panelFrame(), refusal)).toBe(0);
});

test("a build refused for missing test surfaces is said in that criterion's panel, once", async () => {
  await openChain([FACADES, WINDOWS]);
  const refusal = "Choose test surfaces for Spring sun on windows.";
  chainService.runRefusal = { status: 422, body: { detail: refusal, missing_inputs: ["test_surfaces:2"] } };
  showCriterionCards();                                           // the list shown, so the refusal has to open the editor
  await act(async () => buttonIn(pinnedBar(), "Build envelope and massing").click());     // it opens Envelope and massing
  await settle();
  openStep("Criteria");
  expect(editorName()).toBe("Spring sun on windows");
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(panelFrame().querySelector(".criterion-panel-problem")!.textContent).toBe(refusal);
  expect(timesShown(panelFrame(), refusal)).toBe(1);
  await select("Winter sun on facades");
  expect(panelFrame().querySelector(".criterion-panel-problem")).toBeNull();
});

test("Run analysis waits for the test surfaces of every criterion that is on, and names the one without", async () => {
  await openChain([FACADES, { ...WINDOWS, test_surface_files: [] }], { 1: CURRENT, 2: NOT_RUN });
  const runButton = () => buttonIn(pinnedBar(), "Run analysis");
  expect(runButton().disabled).toBe(true);
  expect(reasonOf(runButton())).toBe("Choose test surfaces for Spring sun on windows to run the analysis");
  // A carving change of criterion 1 waits for criterion 2, which needs test surfaces before any analysis.
  expect(panel().textContent).toContain("Choose test surfaces for Spring sun on windows first");
  expect(panel().textContent).not.toContain("Run the analysis for Spring sun on windows first");
  // Shown, it is named too: with several criteria the bar says which one the reason is about.
  await select("Spring sun on windows");
  expect(reasonOf(runButton())).toBe("Choose test surfaces for Spring sun on windows to run the analysis");
  await bypass("Spring sun on windows");
  expect(runButton()).toBeUndefined();                            // criterion 1, alone on, is current: nothing to run
  expect(buttonIn(pinnedBar(), "Build envelope and massing").disabled).toBe(false);
});

test("the reason names the other criterion without test surfaces with a link that opens its Test surfaces; its card is marked", async () => {
  await openChain([FACADES, { ...WINDOWS, test_surface_files: [] }], { 1: CURRENT, 2: NOT_RUN });
  const link = buttonIn(pinnedBar(), "Open Spring sun on windows");
  expect(link).toBeDefined();
  await act(async () => link.click());
  await settle();
  expect(editorName()).toBe("Spring sun on windows");
  const testSurfaces = panelFrame().querySelector<HTMLElement>('[data-section="test_surfaces"] .panel-section-header')!;
  expect(testSurfaces.getAttribute("aria-expanded")).toBe("true");
  // Shown, the criterion is no longer "another" one: the reason stays, without the link
  expect(buttonIn(pinnedBar(), "Open Spring sun on windows")).toBeUndefined();
  showCriterionCards();
  const lineOf = (name: string) => [...container().querySelectorAll(".criterion-card")]
    .find((card) => card.querySelector(".criterion-card-name")?.textContent === name)!.querySelector(".criterion-card-line")!;
  expect(lineOf("Spring sun on windows").classList.contains("criterion-card-line-warning")).toBe(true);
  expect(lineOf("Winter sun on facades").classList.contains("criterion-card-line-warning")).toBe(false);
});

test("with every criterion bypassed Run analysis says to turn one on", async () => {
  await openChain([FACADES, WINDOWS]);
  await bypass("Winter sun on facades");
  await bypass("Spring sun on windows");
  const runButton = buttonIn(pinnedBar(), "Run analysis");
  expect(runButton.disabled).toBe(true);
  expect(reasonOf(runButton)).toBe("Turn on a criterion to run");
});

test("moving an earlier cutoff with auto update runs once, rethresholds the later criterion, and keeps that criterion's histogram", async () => {
  await openChain([FACADES, WINDOWS]);
  chainService.runCriterionStages = { 1: ["thresholding"], 2: ["thresholding"] };
  typeAndLeave(thresholdField(), "1");
  await settle();
  expect(chainService.patches.map((patch) => patch.id)).toEqual(["1"]);
  expect(chainService.runsStarted).toEqual([["thresholding"]]);
  expect(cardLine("Winter sun on facades")).toBe("Running");
  expect(cardLine("Spring sun on windows")).toBe("Updates from Winter sun on facades");
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "1", done: 0, total: 1 });
  run.send({ type: "stage_progress", stage: "thresholding", criterion: "2", done: 0, total: 1 });
  expect(cardLine("Spring sun on windows")).toBe("Running");
  chainService.summaryCriteria = [carvingSummaryOf(FACADES, 50), carvingSummaryOf(WINDOWS, 75)];
  run.send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(chainService.runsStarted).toHaveLength(1);
  const scorePointRequests = chainService.requests.filter((request) => request.startsWith("GET /run/score-points"));
  expect(scorePointRequests).toEqual(["GET /run/score-points?criterion=1", "GET /run/score-points?criterion=1"]);     // at open, after the run
  expect(selectedCardName()).toBe("Winter sun on facades");
  expect(thresholdField().value).toBe("1");
  expect(cardLine("Spring sun on windows")).toBe(volumeLine(25));
});

test("cutoffs moved quickly on two criteria: each value is saved to its own criterion, and neither replaces the other's", async () => {
  await openChain([FACADES, WINDOWS]);
  chainService.runCriterionStages = { 1: ["thresholding"], 2: ["thresholding"] };
  typeAndLeave(thresholdField(), "1");                           // run A, for criterion 1
  await settle();
  typeAndLeave(thresholdField(), "2");                           // waits
  await select("Spring sun on windows");
  typeAndLeave(thresholdField(), "4");                           // waits, beside criterion 1's
  await settle();
  expect(chainService.patches.every((patch) => patch.id === "1")).toBe(true);     // the selection saved criterion 1's typing
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  FakeWebSocket.opened[1].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  const thresholdsOf = (id: string) => chainService.patches.filter((patch) => patch.id === id)
    .map((patch) => thresholdOf(patch.body.values as Record<string, unknown>));
  expect(thresholdsOf("1")[0]).toBe(1);
  expect(thresholdsOf("1").at(-1)).toBe(2);
  expect(thresholdsOf("2")).toEqual([4]);
  expect(chainService.runsStarted).toHaveLength(3);
  expect(chainService.entries.map((entry) => thresholdOf(entry.settings!))).toEqual([2, 4]);
  expect(chainService.entries[0].settings!.start_month).toBe(12);       // criterion 1 kept its own period
});

test("a cutoff waiting for criterion 1's run is saved to criterion 1 after another card is selected", async () => {
  await openChain([FACADES, WINDOWS]);
  chainService.runCriterionStages = { 1: ["thresholding"], 2: ["thresholding"] };
  typeAndLeave(thresholdField(), "1");
  await settle();
  typeAndLeave(thresholdField(), "2");                           // waits for run A
  await select("Spring sun on windows");
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(chainService.patches.filter((patch) => patch.id === "2")).toEqual([]);
  expect(thresholdOf(chainService.entries[0].settings!)).toBe(2);
  expect(thresholdOf(chainService.entries[1].settings!)).toBe(3);
  expect(chainService.runsStarted).toHaveLength(2);              // criterion 1's value runs
  expect(thresholdField().value).toBe("3");                      // criterion 2's panel keeps its own cutoff
});

test("after a reorder a carving run's progress and the cards follow the new chain order", async () => {
  await openChain([FACADES, WINDOWS]);
  const handle = card("Spring sun on windows").querySelector<HTMLElement>(".criterion-card-handle")!;
  await act(async () => handle.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true })));
  await settle();
  await select("Spring sun on windows");
  chainService.runCriterionStages = { 1: ["thresholding"], 2: ["thresholding"] };
  typeAndLeave(thresholdField(), "4");
  await settle();
  expect(stageRows()).toEqual(["Spring sun on windows: Carving | running", "Winter sun on facades: Carving | waiting"]);
  expect(cardLine("Spring sun on windows")).toBe("Running");
  expect(cardLine("Winter sun on facades")).toBe("Updates from Spring sun on windows");
});

test("the selected criterion's carving locks only while its own analysis is out of date; another's keeps a carving change from running", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: OUT_OF_DATE });
  expect(thresholdField().disabled).toBe(false);
  expect(panel().textContent).not.toContain("Settings changed since the analysis.");
  typeAndLeave(thresholdField(), "1");
  await waitForTheSave();
  await settle();
  expect(chainService.patches.map((patch) => patch.id)).toEqual(["1"]);
  expect(chainService.count("POST /runs")).toBe(0);          // tracing criterion 2 is for Run analysis to start (M10)
  expect(panel().textContent).toContain("Run the analysis for Spring sun on windows first");
  await select("Spring sun on windows");
  expect(thresholdField().disabled).toBe(true);
  expect(panel().textContent).toContain("The settings changed since the analysis. Run it again to update the carving.");
});

test("a run refused for criterion 2's settings, seen from criterion 1, names criterion 2; its link selects it, opens the section and focuses the field", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: OUT_OF_DATE });
  chainService.runRefusal = {
    status: 422, body: { field_errors: [{ field: "max_slope_deg", message: "Input should be less than 90" }], grid_plan: null, criterion: "2" },
  };
  await pressRunAnalysis();
  expect(pinnedBar().textContent).toContain("The run stopped on an error.");          // said in the pinned bar; criterion 2 is selected
  await select("Winter sun on facades");
  expect(pinnedBar().textContent).toContain("The run stopped on an error in the settings of Spring sun on windows.");
  togglePanelSection("Carving rule");                             // closed, so the link has to open it
  expect(panelSectionOpen("Carving rule")).toBe(false);
  const link = buttonIn(pinnedBar(), "Go to steepest slope of the envelope of Spring sun on windows");
  await act(async () => link.click());
  await settle();
  expect(panelSectionOpen("Carving rule")).toBe(true);
  expect(container().querySelector('[data-setting="max_slope_deg"]')!.contains(document.activeElement)).toBe(true);
  expect(selectedCardName()).toBe("Spring sun on windows");
});

test("with several criteria the build buttons name the criterion whose analysis they wait for", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: OUT_OF_DATE });
  // The build pinned in Criteria says the same.
  const pinnedBuild = buttonIn(pinnedBar(), "Build envelope and massing");
  expect(pinnedBuild.disabled).toBe(true);
  expect(reasonOf(pinnedBuild)).toBe("Run the analysis for Spring sun on windows first");
  expect(buttonIn(pinnedBar(), "Run analysis").disabled).toBe(false);
  openStep("Envelope and massing");
  for (const [part, label] of [["Envelope", "Build envelope"], ["Building massing", "Build massing"]]) {
    expect(reasonOf(buttonIn(buildPart(part), label))).toBe("Run the analysis for Spring sun on windows first");
  }
});

test("Run analysis asks for the weather file a criterion that is on needs, naming it, also when the shown one needs none", async () => {
  const withoutWeatherFile = (opened: ProjectDetail): ProjectDetail => ({ ...opened, inputs: { ...opened.inputs, weather: [] } });
  await openChain([{ ...ROOFS, id: "1" }, { ...FACADES, id: "2" }], { 1: CURRENT, 2: OUT_OF_DATE }, undefined, [], withoutWeatherFile);
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Add a weather file in Settings to run Winter sun on facades");
  await select("Winter sun on facades");
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Add a weather file in Settings to run Winter sun on facades");
});

test("a criterion that is off is not flagged for a missing weather file", async () => {
  const withoutWeatherFile = (opened: ProjectDetail): ProjectDetail => ({ ...opened, inputs: { ...opened.inputs, weather: [] } });
  await openChain([{ ...ROOFS, id: "1" }, { ...FACADES, id: "2", bypassed: true }], undefined, undefined, [], withoutWeatherFile);
  await select("Winter sun on facades");
  expect(panelSectionOpen("Settings")).toBe(false);
  expect(panel().querySelector(".panel-section-summary-problem")).toBeNull();
  expect(pinnedBar().textContent).not.toContain("weather file");
});

test("a shared setting refused by another criterion's settings is said in the project settings with that criterion's name, on no criterion field", async () => {
  await openChain([FACADES, WINDOWS], undefined, (chain) => {
    chain.configErrorsOf = (values) => (values.voxel_size === 3 ? [{ field: "max_slope_deg", message: "Input should be less than 90" }] : null);
    chain.sharedRefusalCriterion = "2";
  });
  typeAndLeave(voxelSizeField(), "3");
  await waitForTheSave();
  await settle();
  expect(projectSettings()!.textContent).toContain("Spring sun on windows: Steepest slope of the envelope: Input should be less than 90");
  expect(settingsButton().getAttribute("aria-label")).toBe("Settings, 1 setting to fix");
  closeProjectSettings();
  expect(container().querySelector('[data-setting="max_slope_deg"] .setting-error')).toBeNull();     // criterion 1's own field is fine
});

const barButtons = () => [...pinnedBar().querySelectorAll<HTMLButtonElement>(".criteria-run-buttons button")].map((button) => button.textContent);
const updatedLine = () => pinnedBar().querySelector(".run-outcome")?.textContent ?? null;

test("with every criterion current the bar offers only the build, as its primary button", async () => {
  await openChain([FACADES, WINDOWS]);
  expect(barButtons()).toEqual(["Build envelope and massing"]);
  expect(buttonIn(pinnedBar(), "Build envelope and massing").className).toBe("primary-button");
  showCriterionCards();
  expect(barButtons()).toEqual(["Build envelope and massing"]);
});

test("with an analysis out of date the bar offers Run analysis, with the build secondary", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: OUT_OF_DATE });
  expect(barButtons()).toEqual(["Run analysis", "Build envelope and massing"]);
  expect(buttonIn(pinnedBar(), "Build envelope and massing").className).toBe("secondary-button");
  expect(buttonIn(pinnedBar(), "Run analysis").disabled).toBe(false);
});

test("with only a carving out of date the bar offers Update carving, also in the list", async () => {
  await openChain([FACADES, WINDOWS], { 1: CURRENT, 2: THRESHOLD_OUT_OF_DATE });
  expect(barButtons()).toEqual(["Update carving", "Build envelope and massing"]);
  expect(reasonOf(buttonIn(pinnedBar(), "Build envelope and massing"))).toBe("Update the carving before building");
  expect(buttonIn(pinnedBar(), "Run analysis")).toBeUndefined();
  showCriterionCards();
  chainService.runCriterionStages = { 1: [], 2: ["thresholding"] };
  await act(async () => buttonIn(pinnedBar(), "Update carving").click());
  await settle();
  expect(chainService.runsStarted).toEqual([["thresholding"]]);
  expect(stageRows()).toEqual(["Spring sun on windows: Carving | running"]);
  chainService.criterionStages = { 1: CURRENT, 2: CURRENT };
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(barButtons()).toEqual(["Build envelope and massing"]);
  expect(updatedLine()).toBe("Carving updated: Spring sun on windows.");
});

test("a threshold change offers no run while it carves; then a line names the criteria it carved, until a setting puts the chain out of date", async () => {
  await openChain([FACADES, WINDOWS]);
  chainService.runCriterionStages = { 1: ["thresholding"], 2: ["thresholding"] };
  typeAndLeave(thresholdField(), "4");
  await settle();
  expect(barButtons()).toEqual(["Build envelope and massing"]);
  expect(stageRows()).toEqual(["Winter sun on facades: Carving | running", "Spring sun on windows: Carving | waiting"]);
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(barButtons()).toEqual(["Build envelope and massing"]);
  expect(updatedLine()).toBe("Carving updated: Winter sun on facades, Spring sun on windows.");

  typeAndLeave(voxelSizeField(), "2");
  closeProjectSettings();
  await settle();
  expect(barButtons()).toEqual(["Run analysis", "Build envelope and massing"]);
  expect(updatedLine()).toBeNull();
});

test("a carving update of the last criterion names only that one", async () => {
  await openChain([FACADES, WINDOWS]);
  await select("Spring sun on windows");
  chainService.runCriterionStages = { 1: [], 2: ["thresholding"] };
  typeAndLeave(thresholdField(), "4");
  await settle();
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(updatedLine()).toBe("Carving updated: Spring sun on windows.");
});

test("with one criterion the line after a carving update names none", async () => {
  await openChain([FACADES]);
  chainService.runCriterionStages = { 1: ["thresholding"] };
  typeAndLeave(thresholdField(), "4");
  await settle();
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(updatedLine()).toBe("Carving updated.");
});

// The view's Out of date stamp in Carve offers the run the pinned bar offers; it starts the same run.

const viewStamp = () => container().querySelector<HTMLElement>(".viewer-out-of-date");
const stampButton = () => viewStamp()?.querySelector<HTMLButtonElement>("button.viewer-stamp-action") ?? null;
/** The kept voxels of criterion 1 are drawn, so a carving out of date is shown dimmed, with the stamp. */
const withScorePoints = (chain: { scorePointsOf: Record<string, ArrayBuffer> }) => { chain.scorePointsOf = { 1: packScorePoints([0, 1, 2, 3], [1, 0, 1, 1]) }; };

test("in Carve the Out of date stamp offers Update carving when only the carving is out of date, and starts that run", async () => {
  await openChain([FACADES], { 1: THRESHOLD_OUT_OF_DATE }, withScorePoints);
  expect(viewStamp()!.textContent).toContain("Out of date");
  expect(stampButton()!.textContent).toBe("Update carving");
  expect(stampButton()!.disabled).toBe(false);
  chainService.runCriterionStages = { 1: ["thresholding"] };
  await act(async () => stampButton()!.click());
  await settle();
  expect(chainService.runsStarted).toEqual([["thresholding"]]);
  expect(stampButton()).toBeNull();                                  // nothing offered while the run goes
});

test("with the carving updating itself, a change shows Updating at once: no Out of date stamp or Update carving before its run starts", async () => {
  await openChain([FACADES], { 1: CURRENT }, withScorePoints);
  chainService.runCriterionStages = { 1: ["thresholding"] };
  let answerRun = () => {};
  chainService.runsAnswerWhen = new Promise((resolve) => { answerRun = resolve; });
  chainService.criterionStages["1"] = THRESHOLD_OUT_OF_DATE;     // what the stage status says once the change is saved
  typeAndLeave(thresholdField(), "1");
  await waitForTheSave();
  await settle();
  expect(chainService.requests).toContain("POST /runs");          // asked for, not answered yet
  expect(viewStamp()?.textContent ?? "").not.toContain("Out of date");
  expect(stampButton()).toBeNull();
  expect(buttonIn(pinnedBar(), "Update carving")).toBeUndefined();
  await act(async () => answerRun());
  await settle();
  expect(chainService.runsStarted).toEqual([["thresholding"]]);
});

test("in Carve the Out of date stamp offers Run analysis when the analysis is out of date, and starts it", async () => {
  await openChain([FACADES], { 1: OUT_OF_DATE }, withScorePoints);
  expect(stampButton()!.textContent).toBe("Run analysis");
  chainService.runCriterionStages = { 1: ["preprocessing", "thresholding"] };
  await act(async () => stampButton()!.click());
  await settle();
  expect(chainService.runsStarted).toEqual([["thresholding"]]);
  expect(FakeWebSocket.opened).toHaveLength(1);
});

test("the stamp's run is disabled while a run cannot start, with the pinned bar's reason as its title", async () => {
  const withoutWeatherFile = (opened: ProjectDetail): ProjectDetail => ({ ...opened, inputs: { ...opened.inputs, weather: [] } });
  await openChain([FACADES], { 1: THRESHOLD_OUT_OF_DATE }, withScorePoints, [], withoutWeatherFile);
  const barButton = buttonIn(pinnedBar(), "Update carving");
  expect(barButton.disabled).toBe(true);
  expect(stampButton()!.disabled).toBe(true);
  expect(stampButton()!.title).toBe(reasonOf(barButton));
  expect(stampButton()!.title).toBe("Add a weather file in Settings to run this mode");
  await act(async () => stampButton()!.click());
  expect(chainService.runsStarted).toEqual([]);
});

test("in Simulate the stamp offers no run, though the carving is out of date", async () => {
  await openChain([FACADES], { 1: THRESHOLD_OUT_OF_DATE }, withScorePoints);
  expect(stampButton()).not.toBeNull();
  await switchMode("simulate");
  await settle();
  expect(stampButton()).toBeNull();
  await switchMode("design");
  await settle();
  expect(stampButton()!.textContent).toBe("Update carving");
});