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
import { studyPaletteColour } from "../viewer/study_palettes";
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
  expect(reasonOf(runButton())).toBe("A carving run is in progress");

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
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sky_view", [], "refused", "Add study surfaces")]; });
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

const surfacesFromBoxes = () => [...studyPopover()!.querySelectorAll<HTMLLabelElement>(".study-surfaces-from label")]
  .map((label) => ({ label: label.textContent, checked: label.querySelector("input")!.checked, disabled: label.querySelector("input")!.disabled }));
const surfacesFromBox = (label: string) => [...studyPopover()!.querySelectorAll<HTMLLabelElement>(".study-surfaces-from label")]
  .find((each) => each.textContent === label)!.querySelector("input")!;

test("the study surfaces offer the surroundings, greyed without their files, and the ground without a terrain", async () => {
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sky_view", ["facades.obj"], "current")]; });
  await openStudySettings("Sky view factor");
  expect(studyPopover()!.querySelector(".study-files-title")!.textContent).toBe("Study surfaces");
  expect(studyPopover()!.querySelector('[role="group"]')!.getAttribute("aria-labelledby"))
    .toBe(studyPopover()!.querySelector(".study-files-title")!.id);
  expect(surfacesFromBoxes()).toEqual([
    { label: "The surroundings", checked: false, disabled: true }, { label: "The ground around the site", checked: false, disabled: false },
  ]);
  await act(async () => surfacesFromBox("The ground around the site").click());
  await settle();
  expect(simulateService.studyPatches).toEqual([{ id: "1", body: { values: { surfaces_from: ["ground"] } } }]);
  expect(surfacesFromBoxes()[1]).toEqual({ label: "The ground around the site", checked: true, disabled: false });
  expect(studyLine("Sky view factor")).toBe("Out of date");
});

test("with surroundings and a terrain, the study can sample both, and its line names them once its result is current", async () => {
  await openSimulate(undefined, (service) => {
    service.surroundingsFiles = [{ name: "city.obj", triangle_count: 12 }];
    service.terrainFiles = [{ name: "hill.obj", triangle_count: 8 }];
    service.studies = [study("1", "sky_view", ["facades.obj"], "current", null, { surfaces_from: ["terrain"] })];
  });
  expect(studyLine("Sky view factor")).toBe("facades.obj, the terrain");
  await openStudySettings("Sky view factor");
  expect(surfacesFromBoxes()).toEqual([
    { label: "The surroundings", checked: false, disabled: false }, { label: "The terrain", checked: true, disabled: false },
  ]);
  await act(async () => surfacesFromBox("The surroundings").click());
  await settle();
  expect(simulateService.studyPatches).toEqual([{ id: "1", body: { values: { surfaces_from: ["context", "terrain"] } } }]);
  await act(async () => surfacesFromBox("The terrain").click());
  await settle();
  expect(simulateService.studyPatches.at(-1)).toEqual({ id: "1", body: { values: { surfaces_from: ["context"] } } });
  expect(studyPopover()!.querySelector(".study-more-settings")).toBeNull();       // the sources are not a field of More settings
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
  await openSimulate(undefined, (service) => { service.studies = [study("1", "sky_view", [], "refused", "Add study surfaces")]; });
  await openStudySettings("Sky view factor");
  expect(buttonIn(studyPopover()!, "Add study surfaces")).toBeDefined();
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
    service.studies = [study("1", "sky_view", [], "refused", "Add study surfaces"), study("2", "sky_view", ["facades.obj"], "current")];
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
    service.studies = [study("1", "sky_view", [], "refused", "Add study surfaces")];
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
/** Colours by the value in the study's unit (the default), where the target is moved; or by the share of the no-build value. */
const colourByValue = () => act(() => container().querySelector<HTMLButtonElement>(".target-legend-colour-by button:first-child")!.click());
const colourByShare = () => act(() => container().querySelector<HTMLButtonElement>(".target-legend-colour-by button:last-child")!.click());
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

test("the sky dome is the selected study's: another study draws its own, one without a dome draws none", async () => {
  const dome = (count: number) => ({ directions: Array.from({ length: count }, () => [0, 0, 1]), solid_angles: Array(count).fill(0.1),
                                    weights: Array.from({ length: count }, (_, index) => index + 1) });
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sky_view", ["facades.obj"], "current"), study("2", "sky_component", ["facades.obj"], "current"),
                       study("3", "sun_hours", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [90, 90], max_volume: [40, 60] }, "%"), 2: studyValuesOf({ open: [90, 90], max_volume: [40, 60] }, "%"),
                         3: studyValuesOf({ open: [4, 4], max_volume: [1, 2] }) };
    service.skyDomeOf = { 1: dome(3), 2: dome(5) };
  });
  const skyDomeSummary = () => scene().layers.get("sky_dome")?.userData.summary ?? null;
  expect(skyDomeSummary()).toBe("3 patches");
  await selectStudy("Overcast sky component");
  expect(simulateService.requests).toContain("GET /studies/2/sky-patches");
  expect(skyDomeSummary()).toBe("5 patches");
  await selectStudy("Sun hours, 21 Dec");
  expect(skyDomeSummary()).toBeNull();               // sun hours have no patches; Design's dome is not drawn instead
});

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
  expect(cardLines()).toEqual(["keeps 50 % of the no-build value", "mean 2 h", "lowest tenth 1.2 h"]);
  await selectStudy("Sky view factor");
  expect(simulateService.requests).toContain("GET /studies/2/values");
  expect(studyLayerSummary()).toBe("2 points");      // the one layer now holds the second study's values
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sky view factor (%)");    // by value at first
  colourByShare();
  expect(container().querySelector(".target-legend-title")!.textContent).toBe("Sky view factor, share of the no-build value");
  colourByValue();
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
  expect(geometrySegment("Envelope").title).toBe("Out of date in Carve");
  expect(geometrySegment("Massing").getAttribute("aria-disabled")).toBe("true");
  expect(geometrySegment("Massing").title).toBe("Build the massing first");
  expect([...scene().visibleLayers].sort()).toEqual(["max_volume", "study_values"]);
  expect(scene().dimmed.size).toBe(0);         // the envelope out of date in Design is not dimmed here: the switch says so
  expect(scene().envelopeSeeThrough).toBe(false);

  act(() => geometrySegment("Envelope").click());
  await settle();
  expect([...scene().visibleLayers].sort()).toEqual(["envelope", "study_values"]);
  expect(scene().envelopeSeeThrough).toBe(true);
  expect(cardLines()).toEqual(["keeps 88 % of the no-build value (38)", "mean 3.5 h (1.5)", "lowest tenth 3.1 h (1.1)"]);
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
  expect(cardLines()).toEqual(["keeps 50 % of the no-build value", "mean 4 h", "lowest tenth 0.6 h", "at target 50 %"]);
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
  expect(cardLines()).toEqual(["keeps 56 % of the no-build value", "mean 50 %", "lowest tenth 42 %"]);

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
  expect([...legend().querySelectorAll(".target-legend-colour-by button")].map((button) => button.textContent)).toEqual(["Value (h)", "% of no-build"]);
  colourByShare();
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
  colourByShare();
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

test("the palettes are pinned: magma by value, viridis by share; none is offered", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4, 4], max_volume: [1, 2, 3] }) };
  });
  const probe = document.createElement("span");
  const cssColour = (hex: string) => { probe.style.color = hex; return probe.style.color; };
  expect(container().querySelector(".target-legend-palette")).toBeNull();
  expect(targetBar().style.background).toContain(cssColour(studyPaletteColour("magma", 1)));
  const layer = scene().layers.get("study_values")!;
  const colours = (layer as THREE.Mesh).geometry.getAttribute("color") as THREE.BufferAttribute;
  const version = colours.version;
  colourByShare();
  expect(targetBar().style.background).toContain(cssColour(studyPaletteColour("viridis", 1)));
  expect(colours.version).toBeGreaterThan(version);
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

/** The Sun panel under the studies panel, and its parts. */
const sunPanel = () => container().querySelector<HTMLElement>(".sun-panel")!;
const sunView = (label: string) => buttonIn(sunPanel().querySelector<HTMLElement>(".sun-panel-views")!, label);
const sunStatus = () => sunPanel().querySelector('[role="status"]')?.textContent ?? null;
async function clickAndSettle(target: HTMLElement) {
  await act(async () => target.click());
  await settle();
}
/** Opens the project in Simulate with the sun's disc drawable (a 2D canvas, which jsdom does not have), and opens the Sun panel. */
async function openSunPanel(prepare?: Parameters<typeof openSimulate>[1]) {
  const drawing = { fillStyle: "", beginPath() {}, arc() {}, fill() {} };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((kind: string) => (kind === "2d" ? drawing : kind === "webgl2" ? {} : null)) as never);
  await openSimulate(undefined, prepare);
  expect(sunPanel().classList.contains("sun-panel-collapsed")).toBe(true);
  await clickAndSettle(sunPanel().querySelector<HTMLButtonElement>(".sun-panel-toggle")!);
}

test("the open Sun panel shows the sun path, and either the shadows at a moment or the hours in shade over a period, never both", async () => {
  await openSunPanel();
  expect(simulateService.requests).toContain("GET /sun-positions?from=12-21&to=12-21&start=0&end=1440&step=5&time_basis=standard");
  expect(sunStatus()).toBe("Sun 53° above the horizon, 180° from north");
  expect(FakeViewerScene.latest!.sunStudy).toEqual({ sun: [0, -0.6, 0.8], shadows: false, shade: null });
  expect(simulateService.requests).toContain("GET /sun-chart?date=12-21&time_basis=standard");      // opening the panel shows the sun path
  expect(FakeViewerScene.latest!.layers.get("sun_study")).toBeTruthy();

  // The moment: a day strip and a time strip, one handle each.
  await clickAndSettle(sunView("Shadows at a time"));
  expect(FakeViewerScene.latest!.sunStudy.shadows).toBe(true);
  expect([...sunPanel().querySelectorAll('[role="slider"]')].map((slider) => [slider.getAttribute("aria-label"), slider.getAttribute("aria-valuetext")]))
    .toEqual([["Day", "21 December"], ["Time", "12:00"]]);
  const time = sunPanel().querySelector<HTMLElement>('[role="slider"][aria-label="Time"]')!;
  await act(async () => { time.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true, cancelable: true })); });
  await settle();
  expect(sunStatus()).toBe("The sun is below the horizon.");
  expect(FakeViewerScene.latest!.sunStudy.sun).toBeNull();

  // The period: the analysis period's control. The shadows of the moment go; the hours in shade come.
  await clickAndSettle(sunView("Hours in shade"));
  expect(sunPanel().querySelector(".period-control")).not.toBeNull();
  expect(sunPanel().querySelector('[role="slider"][aria-label="Time"]')).toBeNull();
  // 08:00 to 16:00 every 10 minutes, each time the middle of its step: 48 times of 10 minutes, the whole range in sun.
  expect(simulateService.requests).toContain("GET /sun-positions?from=12-21&to=12-21&start=485&end=955&step=10&time_basis=standard");
  const study = FakeViewerScene.latest!.sunStudy;
  expect([study.sun, study.shadows]).toEqual([null, false]);
  expect(study.shade!.directions).toHaveLength(48);
  expect(study.shade!.hoursEach * study.shade!.directions.length).toBeCloseTo(8);
  expect(study.shade!.palette).toBe("viridis");
  expect([...container().querySelectorAll(".viewer-legend h3")].map((title) => title.textContent)).toContain("Hours in shade per day, 08:00 to 16:00, 21 Dec");
  await clickAndSettle(buttonIn(sunPanel(), "Grey"));
  expect(FakeViewerScene.latest!.sunStudy.shade!.palette).toBe("grey");
  // Collapsed, the panel draws nothing of the sun.
  await clickAndSettle(sunPanel().querySelector<HTMLButtonElement>(".sun-panel-toggle")!);
  expect(FakeViewerScene.latest!.sunStudy).toEqual({ sun: null, shadows: false, shade: null });
  expect(FakeViewerScene.latest!.layers.get("sun_study") ?? null).toBeNull();
});

test("the clock of the Sun panel is local standard, local solar or local daylight saving time", async () => {
  await openSunPanel();
  const clock = sunPanel().querySelector<HTMLSelectElement>(".sun-panel-clock select")!;
  expect(sunPanel().querySelector(".sun-panel-body")!.lastElementChild!.classList.contains("sun-panel-clock")).toBe(true);     // at the end
  expect([...clock.options].map((option) => option.textContent)).toEqual(["Local standard time", "Local solar time", "Local daylight saving time"]);
  await act(async () => { clock.value = "solar"; clock.dispatchEvent(new Event("change", { bubbles: true })); });
  await settle();
  expect(simulateService.requests).toContain("GET /sun-positions?from=12-21&to=12-21&start=0&end=1440&step=5&time_basis=solar");
});

test("without a weather file the Sun panel says one is needed and reads nothing", async () => {
  await openSunPanel((service) => { service.hasWeatherFile = false; });
  expect(sunPanel().textContent).toContain("Add a weather file in Carve (Inputs) to see the sun");
  expect(simulateService.requests.some((request) => request.includes("/sun-"))).toBe(false);
});

test("a study run before its sky patches were kept lists the Sky dome as missing, saying to run it again", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sky_view", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [90, 90], max_volume: [40, 60] }, "%") };       // no skyDomeOf: 404
  });
  await act(async () => buttonIn(container(), "Layers").click());
  const entry = [...container().querySelectorAll("li")].find((item) => item.textContent?.startsWith("Sky dome"))!;
  expect(entry.querySelector("input")!.disabled).toBe(true);
  expect(entry.textContent).toContain("Run the study again to see its sky dome");
});

test("the switch beside Studies hides the selected study from the view and shows it again", async () => {
  await openSimulate(undefined, (service) => {
    service.studies = [study("1", "sun_hours", ["facades.obj"], "current")];
    service.valuesOf = { 1: studyValuesOf({ open: [4, 4, 4], max_volume: [1, 2, 3] }) };
  });
  const shown = () => studiesPanel().querySelector<HTMLInputElement>('.studies-panel-shown input[role="switch"]')!;
  expect(shown().checked).toBe(true);
  expect(studyLayerSummary()).toBe("3 points");
  await clickAndSettle(shown());
  expect(studyLayerSummary()).toBeNull();
  expect(container().querySelector(".target-legend")).toBeNull();
  expect(container().querySelector(".result-card")).toBeNull();
  await clickAndSettle(shown());
  expect(studyLayerSummary()).toBe("3 points");
});
