// The Design | Simulate mode of the open workspace: Simulate hides the steps and gives the view the whole window; Design brings
// them back as they were. The switch itself, and what the page does with the mode around opening and renaming, are in App.test.tsx.
// Then the studies panel over the view in Simulate: the studies of the project, Add study, a study's popover and Run (the simulation
// is a run of the run loop, one job at a time with the runs of Design).
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import type * as THREE from "three";
import { studyValuesOf } from "../simulate/study_values_for_test";
import { TARGET_SAVE_DELAY_MILLISECONDS } from "../simulate/use_study_view";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import {
  CARVING, ENVELOPE, NOTHING_RUN, FakeService, buttonIn, container, endWorkspaceTest, openStep, openWorkspace, pinnedBar, pressRunAnalysis, project, reasonOf,
  settle, startWorkspaceTest, stepRow, switchMode,
} from "./project_workspace_for_test";
import {
  addStudyButton, addStudyMenuItems, chooseAddStudy, openSimulate, openStudySettings, runButton, selectedStudyName, simulateService, study,
  studyLine, studyNames, studyPopover, studyRow, studyRows, studiesPanel,
} from "./simulate_service_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const panel = () => container().querySelector<HTMLElement>(".workspace-panel")!;
const stepsScroller = () => container().querySelector<HTMLElement>(".step-list")!;
const openStepTitle = () => container().querySelector(".step-open .step-title")?.textContent;

/** jsdom does not lay out, so scrollTop does nothing there: a settable one stands in, which a browser clears when the element is hidden. */
function makeScrollable(element: HTMLElement) {
  let top = 0;
  Object.defineProperty(element, "scrollTop", { get: () => top, set: (value: number) => { top = value; }, configurable: true });
}
const scrollTo = (element: HTMLElement, top: number) => act(() => {
  element.scrollTop = top;
  element.dispatchEvent(new Event("scroll"));
});

test("Simulate hides the steps and Design shows them again with the same step open and scrolled", async () => {
  await openWorkspace(new FakeService(NOTHING_RUN, null), project(NOTHING_RUN));
  makeScrollable(stepsScroller());
  openStep("Criteria");
  scrollTo(stepsScroller(), 120);
  expect(panel().hidden).toBe(false);

  await switchMode("simulate");
  expect(panel().hidden).toBe(true);
  expect(container().querySelector(".workspace-panel")).not.toBeNull();       // hidden, not unmounted: the open step and its form stay
  stepsScroller().scrollTop = 0;       // what a browser does to an element that is not displayed

  await switchMode("design");
  expect(panel().hidden).toBe(false);
  expect(openStepTitle()).toBe("Criteria");
  expect(stepRow("Criteria").querySelector(".step-content")).not.toBeNull();
  expect(stepsScroller().scrollTop).toBe(120);
});

test("Inspect hides the steps as Simulate does, and Design brings them back", async () => {
  await openWorkspace(new FakeService(NOTHING_RUN, null), project(NOTHING_RUN));
  await switchMode("inspect");
  expect(panel().hidden).toBe(true);
  await switchMode("design");
  expect(panel().hidden).toBe(false);
});

test("a scroll event that comes while the steps are hidden does not replace the scroll they had", async () => {
  await openWorkspace(new FakeService(NOTHING_RUN, null), project(NOTHING_RUN));
  makeScrollable(stepsScroller());
  scrollTo(stepsScroller(), 80);
  await switchMode("simulate");
  scrollTo(stepsScroller(), 0);       // the browser reporting the reset
  await switchMode("design");
  expect(stepsScroller().scrollTop).toBe(80);
});

test("Simulate puts its own content over the 3D view, and Design takes it away", async () => {
  await openWorkspace(new FakeService(NOTHING_RUN, null), project(NOTHING_RUN));
  expect(container().querySelector(".simulate-view")).toBeNull();
  await switchMode("simulate");
  expect(container().querySelector(".workspace-view .simulate-view")).not.toBeNull();
  await switchMode("design");
  expect(container().querySelector(".simulate-view")).toBeNull();
});

test("in Simulate the empty view does not offer to add files, which Inputs in the hidden steps would take", async () => {
  const opened = project(NOTHING_RUN);
  await openWorkspace(new FakeService(NOTHING_RUN, null), { ...opened, inputs: { max_volume: [], test_surfaces: [], weather: [] } });
  expect(container().querySelector(".viewer-empty-state")).not.toBeNull();
  await switchMode("simulate");
  expect(container().querySelector(".viewer-empty-state")).toBeNull();
  await switchMode("design");
  expect(container().querySelector(".viewer-empty-state")).not.toBeNull();
});

test("a new project's Simulate shows an empty panel with Add study and no Run", async () => {
  await openSimulate();
  expect(simulateService.requests).toContain("GET /studies");
  expect(studiesPanel()).not.toBeNull();
  expect(studyRows()).toEqual([]);
  expect(addStudyButton()).toBeDefined();
  expect(runButton()).toBeUndefined();
});

test("Add study lists the criteria first as Like <name>, then the metrics, Sun hours disabled without a weather file", async () => {
  await openSimulate(undefined, (service) => { service.hasWeatherFile = false; });
  act(() => addStudyButton().click());
  expect(addStudyButton().getAttribute("aria-expanded")).toBe("true");
  expect(addStudyMenuItems()).toEqual([
    { label: "Like Winter sun on facades", disabled: false },
    { label: "Sun hours", disabled: true },
    { label: "Solar energy", disabled: true },
    { label: "Useful solar gains", disabled: true },
    { label: "Overcast sky component", disabled: false },
    { label: "Cooling sky", disabled: false },
    { label: "Sky view factor", disabled: false },
  ]);
  const sunHours = [...container().querySelectorAll<HTMLButtonElement>('.add-study-menu [role="menuitem"]')][1];
  expect(document.getElementById(sunHours.getAttribute("aria-describedby")!)!.textContent).toBe("Needs a weather file");
  await act(async () => sunHours.click());       // a disabled item adds nothing
  expect(simulateService.requests).not.toContain("POST /studies");
});

test("Like Winter sun on facades adds a study with the criterion's files and selects it", async () => {
  await openSimulate();
  await chooseAddStudy("Like Winter sun on facades");
  expect(simulateService.requests).toContain("POST /studies");
  expect(studyNames()).toEqual(["Sun hours, 21 Dec"]);
  expect(selectedStudyName()).toBe("Sun hours, 21 Dec");
  expect(studyLine("Sun hours, 21 Dec")).toBe("Not run yet");
  // Its settings open beside it, with the criterion's files.
  expect(studyPopover()).not.toBeNull();
  expect([...studyPopover()!.querySelectorAll(".input-file-name")].map((name) => name.textContent)).toEqual(["facades.obj"]);
});

test("Run posts /simulate, shows progress, and refreshes the studies when it finishes", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sun_hours", ["facades.obj"])]; });
  const studiesReads = simulateService.count("GET /studies");
  await act(async () => runButton().click());
  await settle();
  expect(simulateService.requests).toContain("POST /simulate");
  expect(FakeWebSocket.opened).toHaveLength(1);
  const simulation = FakeWebSocket.opened[0];
  simulation.send({ type: "stage_progress", stage: "simulate", criterion: null, study: "1", done: 2, total: 5 });
  expect(studiesPanel().querySelector(".run-progress")!.textContent).toContain("Sun hours, 21 Dec2 of 5 batches");
  simulateService.studies = [study("1", "sun_hours", ["facades.obj"], "current")];
  simulateService.valuesOf = { 1: studyValuesOf({ open: [4, 4, 4], max_volume: [1, 2, 3] }) };
  simulation.send({ type: "run_finished", stages: ["simulate"], files: [] });
  await settle();
  expect(simulateService.count("GET /studies")).toBe(studiesReads + 1);
  expect(studyLine("Sun hours, 21 Dec")).toBe("facades.obj");
  expect(studyLayerSummary()).toBe("3 points");      // the result is on the view without pressing the study
  expect(simulateService.runsStarted).toEqual([]);       // no pipeline run
});

test("Run is unavailable during a Design run, and Design's Run analysis during a simulation", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sun_hours", ["facades.obj"])]; });
  await switchMode("design");
  await pressRunAnalysis();
  expect(FakeWebSocket.opened).toHaveLength(1);
  await switchMode("simulate");
  await settle();
  expect(runButton().disabled).toBe(true);
  expect(reasonOf(runButton())).toBe("A Design run is in progress");

  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();
  expect(runButton().disabled).toBe(false);
  await act(async () => runButton().click());
  await settle();
  expect(FakeWebSocket.opened).toHaveLength(2);
  await switchMode("design");
  const runAnalysis = buttonIn(pinnedBar(), "Run analysis");
  expect(runAnalysis.disabled).toBe(true);
  expect(reasonOf(runAnalysis)).toBe("A simulation is in progress");
});

test("changing the period in the popover saves the study and renames it", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sun_hours", ["facades.obj"], "current")]; });
  await openStudySettings("Sun hours, 21 Dec");
  const popover = studyPopover()!;
  expect(popover.getAttribute("role")).toBe("dialog");
  expect(popover.querySelector("h3")!.textContent).toBe("Sun hours, 21 Dec");
  await act(async () => buttonIn(popover, "21 June").click());
  await settle();
  expect(simulateService.studyPatches).toEqual([{ id: "1", body: { values: { start_month: 6, end_month: 6 } } }]);
  expect(studyNames()).toEqual(["Sun hours, 21 Jun"]);
  expect(studyPopover()!.querySelector("h3")!.textContent).toBe("Sun hours, 21 Jun");
  expect(studyLine("Sun hours, 21 Jun")).toBe("Out of date");
});

test("a study's settings take the focus, use a stored file, and Escape gives the focus back to its settings button", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sky_view", [], "refused", "Add test surfaces")]; });
  await openStudySettings("Sky view factor");
  const settingsButton = studyRow("Sky view factor").querySelector<HTMLButtonElement>(".study-row-settings")!;
  expect(settingsButton.getAttribute("aria-expanded")).toBe("true");
  expect(settingsButton.getAttribute("aria-controls")).toBe(studyPopover()!.id);
  expect(document.activeElement).toBe(studyPopover()!.querySelector('input[type="text"]'));
  expect(selectedStudyName()).toBe("Sky view factor");
  await act(async () => buttonIn(studyPopover()!, "Use").click());
  await settle();
  expect(simulateService.requests).toContain("PUT /studies/1/test-surfaces/facades.obj");
  expect([...studyPopover()!.querySelectorAll(".input-file-name")].map((name) => name.textContent)).toEqual(["facades.obj"]);
  expect(studyLine("Sky view factor")).toBe("Not run yet");

  act(() => studyPopover()!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })));
  expect(studyPopover()).toBeNull();
  expect(document.activeElement).toBe(settingsButton);
  expect(settingsButton.getAttribute("aria-expanded")).toBe("false");
});

/** Chooses the files in the popover's file input, as the user does with the add button. */
async function chooseStudyFiles(...files: File[]) {
  const picker = studyPopover()!.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(picker, "files", { value: files, configurable: true });
  act(() => picker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
}
const popoverFiles = () => [...studyPopover()!.querySelectorAll(".input-file-name")].map((name) => name.textContent);

test("the popover's files box takes a new file and lists it on the study", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sky_view", [], "refused", "Add test surfaces")]; });
  await openStudySettings("Sky view factor");
  expect(buttonIn(studyPopover()!, "Add test surfaces")).toBeDefined();
  await chooseStudyFiles(new File(["v 0 0 0"], "roof.obj"));
  expect(simulateService.requests).toContain("POST /studies/1/test-surfaces");
  expect(simulateService.requests.some((request) => request.startsWith("POST /inputs/") || request.startsWith("POST /criteria/"))).toBe(false);
  expect(popoverFiles()).toEqual(["roof.obj"]);
  expect(studyLine("Sky view factor")).toBe("Not run yet");
  expect(simulateService.requests).toContain("GET /inputs/test_surfaces");           // the stored files are asked for again
  expect(simulateService.storedFileCount("roof.obj")).toBe(1);
  expect(studyPopover()!.querySelector(".input-box-problem")).toBeNull();
});

test("a new file with a stored name replaces it: the criteria and studies that list it follow the new content", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sky_view", [], "refused", "Add test surfaces"), study("2", "sky_view", ["facades.obj"], "current")];
  });
  await openStudySettings("Sky view factor");
  const statusReads = simulateService.count("GET /stage-status");
  await chooseStudyFiles(new File(["v 0 0 1"], "facades.obj"));
  expect(simulateService.replacedFiles).toEqual(["facades.obj"]);
  expect(popoverFiles()).toEqual(["facades.obj"]);
  expect(simulateService.storedFileCount("facades.obj")).toBe(1);
  expect(simulateService.count("GET /stage-status")).toBe(statusReads + 1);          // the criterion that lists it is out of date
  expect(simulateService.count("GET /studies")).toBeGreaterThan(1);
  expect(studyLine("Sky view factor")).toBe("Not run yet");
});

test("a file the service refuses is named with its reason, and the study keeps what it had", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sky_view", [], "refused", "Add test surfaces")];
    service.uploadRefusal = "It is not a readable mesh.";
  });
  await openStudySettings("Sky view factor");
  await chooseStudyFiles(new File(["x"], "broken.obj"));
  expect(studyPopover()!.querySelector(".input-box-problem")!.textContent).toContain("broken.obj");
  expect(studyPopover()!.querySelector(".input-box-problem")!.textContent).toContain("It is not a readable mesh.");
  expect(popoverFiles()).toEqual([]);
});

// Results on the view: the selected study's values on the geometry shown, the geometry switch, the target legend and the result card.

const scene = () => FakeViewerScene.latest!;
const studyLayerSummary = () => scene().layers.get("study_values")?.userData.summary ?? null;
const geometrySegment = (label: string) => [...container().querySelectorAll<HTMLButtonElement>(".geometry-switch-segment")]
  .find((button) => button.textContent === label)!;
const targetMark = () => container().querySelector<HTMLElement>('.target-legend [role="slider"][data-end="low"]')!;
const targetBar = () => container().querySelector<HTMLElement>(".target-legend-bar")!;
/** Colours by the value in the study's unit, where the target is moved (the default is the share of the open-site value). */
const colourByValue = () => act(() => container().querySelector<HTMLButtonElement>(".target-legend-colour-by button:last-child")!.click());
const cardLines = () => [...container().querySelectorAll(".result-card-line")].map((line) => line.textContent);
const stamp = () => container().querySelector(".viewer-out-of-date");
const BUILT_ENVELOPE = { carving: CARVING, envelope: { ...ENVELOPE, mesh_file: "export.obj" }, massing: null };

async function selectStudy(name: string) {
  act(() => studyRow(name).querySelector<HTMLButtonElement>(".study-row-select")!.click());
  await settle();
}

const waitForTargetSave = async () => {
  await act(async () => { await vi.advanceTimersByTimeAsync(TARGET_SAVE_DELAY_MILLISECONDS + 50); });
  await settle();
};

function pointerOnTargetBar(type: "pointerdown" | "pointermove" | "pointerup", clientX: number) {
  act(() => { targetBar().dispatchEvent(new PointerEvent(type, { bubbles: true, clientX, pointerId: 1, button: 0 })); });
}

test("selecting another study draws its values; only one study is drawn", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current"), study("2", "sky_view", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4, 4], max_volume: [1, 2, 3] }), 2: studyValuesOf({ open: [90, 90], max_volume: [40, 60] }, "%") };
  });
  expect(studyLayerSummary()).toBe("3 points");    // the first study with a result is on the view at once
  await selectStudy("Sky view factor");
  await selectStudy("Sun hours, 21 Dec");
  expect(simulateService.requests).toContain("GET /studies/1/values");
  expect(studyLayerSummary()).toBe("3 points");
  expect(scene().visibleLayers.has("study_values")).toBe(true);
  expect(cardLines()).toEqual(["keeps 50 % of the open-site value", "mean 2 h", "lowest tenth 1.2 h"]);
  await selectStudy("Sky view factor");
  expect(simulateService.requests).toContain("GET /studies/2/values");
  expect(studyLayerSummary()).toBe("2 points");      // the one layer now holds the second study's values
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sky view factor, share of the open-site value");
  colourByValue();
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sky view factor (%)");
  expect(stamp()).toBeNull();
  // A study that has not run has nothing to draw.
  await chooseAddStudy("Cooling sky");
  expect(simulateService.requests).not.toContain("GET /studies/3/values");
  expect(studyLayerSummary()).toBeNull();
  expect(container().querySelector(".result-card")).toBeNull();
  expect(container().querySelector(".target-legend")).toBeNull();
});

test("an out of date study's values stay drawn, dimmed, with the stamp", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sun_hours", ["facades.obj"], "out_of_date"), study("2", "sky_view", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4], max_volume: [1, 2] }), 2: studyValuesOf({ open: [90], max_volume: [40] }, "%") };
  });
  await selectStudy("Sun hours, 21 Dec");
  expect(studyLayerSummary()).toBe("2 points");
  expect(scene().dimmed.has("study_values")).toBe(true);
  expect(stamp()!.textContent).toContain("Out of date");
  await selectStudy("Sky view factor");
  expect(scene().dimmed.has("study_values")).toBe(false);
  expect(stamp()).toBeNull();
});

test("the geometry shown uses Design's layers, without the criteria's test surfaces; Envelope once built, marked out of date in Design", async () => {
  await openSimulate(undefined, (service) => {
    service.summary = BUILT_ENVELOPE;
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4], max_volume: [1, 2], envelope: [3, 4] }) };
  }, { exporting: "out_of_date" });
  await selectStudy("Sun hours, 21 Dec");
  expect(geometrySegment("Envelope").getAttribute("aria-disabled")).toBeNull();
  expect(geometrySegment("Envelope").title).toBe("Out of date in Design");
  expect(geometrySegment("Massing").getAttribute("aria-disabled")).toBe("true");
  expect(geometrySegment("Massing").title).toBe("Build the massing first");
  expect([...scene().visibleLayers].sort()).toEqual(["max_volume", "study_values"]);
  expect(scene().dimmed.size).toBe(0);         // the envelope out of date in Design is not dimmed here: the switch says so
  expect(scene().envelopeSeeThrough).toBe(false);

  act(() => geometrySegment("Envelope").click());
  await settle();
  expect([...scene().visibleLayers].sort()).toEqual(["envelope", "study_values"]);
  expect(scene().envelopeSeeThrough).toBe(true);
  expect(cardLines()).toEqual(["keeps 88 % of the open-site value (38)", "mean 3.5 h (1.5)", "lowest tenth 3.1 h (1.1)"]);
  expect(stamp()).toBeNull();

  // Back in Design the steps' layers and the envelope's own look come back, without the study.
  await switchMode("design");
  expect(scene().envelopeSeeThrough).toBe(false);
  expect(studyLayerSummary()).toBeNull();
  expect(container().querySelector(".geometry-switch")).toBeNull();
  // Simulate again: the same study on the same geometry, its values read again (they are let go in Design).
  const reads = simulateService.count("GET /studies/1/values");
  await switchMode("simulate");
  await settle();
  expect(simulateService.count("GET /studies/1/values")).toBe(reads + 1);
  expect(geometrySegment("Envelope").getAttribute("aria-pressed")).toBe("true");
  expect(studyLayerSummary()).toBe("2 points");
});

test("dragging the target mark or pressing arrow keys moves the target and saves it with the study", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [8, 8, 8, 8], max_volume: [0, 2, 6, 8] }) };
  });
  await selectStudy("Sun hours, 21 Dec");
  colourByValue();
  const layer = scene().layers.get("study_values")!;
  const colours = (layer as THREE.Mesh).geometry.getAttribute("color") as THREE.BufferAttribute;
  const coloursVersion = colours.version, redraws = scene().redraws;
  // jsdom lays nothing out: the bar is 200 px wide, 0 to 8 h, 25 px an hour.
  targetBar().getBoundingClientRect = () => ({ left: 0, width: 200, top: 0, height: 12, right: 200, bottom: 12, x: 0, y: 0, toJSON: () => ({}) });
  pointerOnTargetBar("pointerdown", 100);
  pointerOnTargetBar("pointermove", 120);
  pointerOnTargetBar("pointermove", 125);
  expect(simulateService.studyPatches).toEqual([]);         // nothing saved while dragging
  pointerOnTargetBar("pointerup", 125);
  await settle();
  // Shown at once: the mark, the card, and the same layer recoloured in place (points below the target muted).
  expect(targetMark().getAttribute("aria-valuenow")).toBe("5");
  expect(cardLines()).toEqual(["keeps 50 % of the open-site value", "mean 4 h", "lowest tenth 0.6 h", "at target 50 %"]);
  expect(scene().layers.get("study_values")).toBe(layer);
  expect(colours.version).toBeGreaterThan(coloursVersion);
  expect(scene().redraws).toBeGreaterThan(redraws);
  await waitForTargetSave();
  expect(simulateService.studyPatches).toEqual([{ id: "1", body: { target: 5 } }]);
  expect(studyLine("Sun hours, 21 Dec")).toBe("facades.obj");             // the target leaves the result current

  // Several key presses, as a held arrow key gives: the mark moves at each, and the target is saved once, at the value it ended on.
  act(() => targetMark().focus());
  for (let press = 0; press < 3; press++) {
    act(() => { targetMark().dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(50); });
  }
  expect(targetMark().getAttribute("aria-valuenow")).toBe("5.24");
  expect(simulateService.studyPatches).toHaveLength(1);
  await waitForTargetSave();
  expect(simulateService.studyPatches).toEqual([{ id: "1", body: { target: 5 } }, { id: "1", body: { target: 5.24 } }]);
  expect(scene().layers.get("study_values")).toBe(layer);

  act(() => { targetMark().dispatchEvent(new KeyboardEvent("keydown", { key: "Delete", bubbles: true, cancelable: true })); });
  await waitForTargetSave();
  expect(simulateService.studyPatches.at(-1)).toEqual({ id: "1", body: { target: null } });
  expect(simulateService.studyPatches).toHaveLength(3);
  expect(targetMark().getAttribute("aria-valuetext")).toBe("0 h");          // no target: the low end is back at 0
  expect(cardLines()).toHaveLength(3);
});

test("a study run before the envelope was built waits on Envelope with the reason, shows the maximum volume, and keeps the stamp", async () => {
  await openSimulate(undefined, (service) => {
    service.summary = BUILT_ENVELOPE;
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current"), study("2", "sky_view", ["facades.obj"], "out_of_date")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4], max_volume: [1, 2], envelope: [3, 4] }),
                         2: studyValuesOf({ open: [90, 90, 90], max_volume: [40, 50, 60] }, "%") };       // no envelope column
  }, { exporting: "current" });
  await selectStudy("Sun hours, 21 Dec");
  act(() => geometrySegment("Envelope").click());
  await settle();
  expect(scene().visibleLayers.has("envelope")).toBe(true);

  await selectStudy("Sky view factor");
  expect(geometrySegment("Envelope").getAttribute("aria-disabled")).toBe("true");
  expect(geometrySegment("Envelope").title).toBe("Run the study again to see it on the envelope");
  expect(reasonOf(geometrySegment("Envelope"))).toBe("Run the study again to see it on the envelope");
  expect(geometrySegment("Max volume").getAttribute("aria-pressed")).toBe("true");
  expect([...scene().visibleLayers].sort()).toEqual(["max_volume", "study_values"]);
  expect(studyLayerSummary()).toBe("3 points");
  expect(scene().dimmed.has("study_values")).toBe(true);
  expect(stamp()!.textContent).toContain("Out of date");
  expect(cardLines()).toEqual(["keeps 56 % of the open-site value", "mean 50 %", "lowest tenth 42 %"]);

  // The first study has the envelope: the choice comes back.
  await selectStudy("Sun hours, 21 Dec");
  expect(geometrySegment("Envelope").getAttribute("aria-pressed")).toBe("true");
  expect(stamp()).toBeNull();
});

test("by share the two ends are percentages kept for the study while the app is open, not saved; the value button names the unit", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4], max_volume: [1, 4] }) };
  });
  const legend = () => container().querySelector(".target-legend")!;
  expect([...legend().querySelectorAll(".target-legend-colour-by button")].map((button) => button.textContent)).toEqual(["% of open site", "Value (h)"]);
  expect(targetMark().getAttribute("aria-valuetext")).toBe("0\u00a0%");
  const layer = scene().layers.get("study_values")!;
  const colours = (layer as THREE.Mesh).geometry.getAttribute("color") as THREE.BufferAttribute;
  const version = colours.version;
  act(() => targetMark().focus());
  act(() => { targetMark().dispatchEvent(new KeyboardEvent("keydown", { key: "PageUp", bubbles: true, cancelable: true })); });
  expect(targetMark().getAttribute("aria-valuetext")).toBe("10\u00a0%");
  expect(colours.version).toBeGreaterThan(version);                  // the same layer recoloured
  await waitForTargetSave();
  expect(simulateService.studyPatches).toEqual([]);                  // by share nothing is saved
  colourByValue();
  expect(targetMark().getAttribute("aria-valuetext")).toBe("0\u00a0h");   // by value the ends are the study's own
  act(() => legend().querySelector<HTMLButtonElement>(".target-legend-colour-by button")!.click());
  expect(targetMark().getAttribute("aria-valuetext")).toBe("10\u00a0%");  // the share range is kept
});

test("the stamp shows while the selected study is out of date, even before its values are drawn", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sun_hours", ["facades.obj"], "out_of_date")]; });     // no values
  await selectStudy("Sun hours, 21 Dec");
  expect(studyLayerSummary()).toBeNull();
  expect(stamp()!.textContent).toContain("Out of date");
});

test("while a study's popover is open the geometry switch moves to the right of it, so the popover does not cover the switch", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sun_hours", ["facades.obj"], "current")]; });
  const bar = () => container().querySelector<HTMLElement>(".simulate-geometry-bar")!;
  expect(bar().classList.contains("simulate-geometry-bar-beside-popover")).toBe(false);
  await openStudySettings("Sun hours, 21 Dec");
  expect(bar().classList.contains("simulate-geometry-bar-beside-popover")).toBe(true);
  act(() => studyPopover()!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })));
  expect(bar().classList.contains("simulate-geometry-bar-beside-popover")).toBe(false);
});

test("the palette is magma at first, can be chosen on the legend, and is kept in the browser", async () => {
  window.localStorage.clear();
  try {
    await openSimulate(undefined, (service) => {
      service.studies = [study("1", "sun_hours", ["facades.obj"], "current")];
      service.valuesOf = { 1: studyValuesOf({ open: [4, 4, 4], max_volume: [1, 2, 3] }) };
    });
    const select = () => container().querySelector<HTMLSelectElement>(".target-legend-palette")!;
    expect(select().value).toBe("magma");
    const layer = scene().layers.get("study_values")!;
    const colours = (layer as THREE.Mesh).geometry.getAttribute("color") as THREE.BufferAttribute;
    const version = colours.version;
    act(() => { select().value = "viridis"; select().dispatchEvent(new Event("change", { bubbles: true })); });
    expect(select().value).toBe("viridis");
    expect(colours.version).toBeGreaterThan(version);
    expect(window.localStorage.getItem("usc.studyPalette")).toBe("viridis");
  } finally {
    window.localStorage.clear();
  }
});

test("during a run, a study whose values are not read yet says they are shown when the run ends", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current"), study("2", "sky_view", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4, 4], max_volume: [1, 2, 3] }), 2: studyValuesOf({ open: [90, 90], max_volume: [40, 60] }, "%") };
  });
  const note = () => container().querySelector(".study-view-note");
  await selectStudy("Sun hours, 21 Dec");
  expect(note()).toBeNull();
  await act(async () => runButton().click());
  await settle();
  expect(note()).toBeNull();                               // the first study's values are on the view already
  expect(studyLayerSummary()).toBe("3 points");
  await selectStudy("Sky view factor");
  expect(studyLayerSummary()).toBeNull();
  expect(note()!.textContent).toBe("Shown when the run ends");
  expect(note()!.getAttribute("role")).toBe("status");
  FakeWebSocket.opened[0].send({ type: "run_finished", stages: ["simulate"], files: [] });
  await settle();
  expect(note()).toBeNull();
  expect(studyLayerSummary()).toBe("2 points");
});
