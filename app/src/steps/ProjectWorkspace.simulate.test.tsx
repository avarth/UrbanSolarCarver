// The Design | Simulate mode of the open workspace: Simulate hides the steps and gives the view the whole window; Design brings
// them back as they were. The switch itself, and what the page does with the mode around opening and renaming, are in App.test.tsx.
// Then the studies panel over the view in Simulate: the studies of the project, Add study, a study's popover and Run (the simulation
// is a run of the run loop, one job at a time with the runs of Design).
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import {
  NOTHING_RUN, FakeService, buttonIn, container, endWorkspaceTest, openStep, openWorkspace, pinnedBar, pressRunAnalysis, project, reasonOf, settle,
  startWorkspaceTest, stepRow, switchMode,
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
    { label: "Useful solar energy", disabled: true },
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
  simulation.send({ type: "run_finished", stages: ["simulate"], files: [] });
  await settle();
  expect(simulateService.count("GET /studies")).toBe(studiesReads + 1);
  expect(studyLine("Sun hours, 21 Dec")).toBe("facades.obj");
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
  expect(studyPopover()!.querySelector(".input-add")).toBeNull();       // no new files yet: the project's stored ones only
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
