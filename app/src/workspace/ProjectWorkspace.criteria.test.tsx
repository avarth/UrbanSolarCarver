// The open project's steps for one criterion, against a fake service: Site holds the site, the project settings the shared settings,
// and Criteria opens straight on the criterion, which switches the project's surface sets (the Site step's Test surfaces) on and off
// through its own routes. The last tests are of what the
// Criteria step shows, the list or the editor of one criterion: how it opens, what it keeps, and what leads to a criterion's settings.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ProjectDetail } from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import type { PipelineStage, StageState } from "../stages";
import { FACADES, ROOFS, WINDOWS, deleteCriterion, openChain, select, service as chainService } from "./chain_service_for_test";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, NOTHING_RUN, TRIANGLE_OBJ, addWeatherFileInSettings, buttonIn, container, criterionEntry, endWorkspaceTest, openStep, closeProjectSettings, openProjectSettings, projectSettings, settingsButton,
  openPanelSection, openWorkspace, pinnedBar, pressRunAnalysis, project, reasonOf, settle, showCriterionCards, showCriterionEditor, startWorkspaceTest, stepIsOpen, stepRow, type,
  surfaceSetSwitches, surfaceSetsBox, unmountWorkspace, voxelSizeField,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let service: FakeService;
beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const EVERY_STAGE_CURRENT: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
const panel = () => container().querySelector<HTMLElement>(".criterion-panel");
const setSwitches = () => panel()!.querySelector<HTMLElement>(".surface-set-switches")!;
const setSwitch = (name: string) => setSwitches().querySelector<HTMLInputElement>(`[aria-label="Use ${name}"]`)!;
const setNamesIn = (box: HTMLElement) => [...box.querySelectorAll(".input-file-name")].map((name) => name.textContent);
const field = (setting: string) => container().querySelector(`[data-setting="${setting}"]`);
const stepTitles = () => [...container().querySelectorAll(".step-title")].map((title) => title.textContent);

test("the steps are Site, Criteria, Envelope and massing and Export; the shared settings are behind the Settings button", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  expect(stepTitles()).toEqual(["Site", "Criteria", "Envelope and massing", "Export"]);
  expect(settingsButton().textContent).toBe("Settings");
});

test("one criterion shows its row in the list, with the switch on and no drag handle", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  const step = stepRow("Criteria");
  expect(panel()).not.toBeNull();                                                      // the criterion open at once
  showCriterionCards();
  const rows = [...step.querySelectorAll(".criterion-list .criterion-card")];
  expect(rows).toHaveLength(1);
  expect(rows[0].querySelector(".criterion-card-swatch")).not.toBeNull();
  expect(rows[0].querySelector(".criterion-card-name")!.textContent).not.toBe("");
  expect(rows[0].querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(true);
  expect(rows[0].querySelector(".criterion-card-line")!.textContent).not.toBe("Off");
  expect(rows[0].querySelector('[role="switch"]')!.getAttribute("aria-label")).toMatch(/^Use /);
  expect(step.querySelector("[draggable='true'], .criterion-card-handle")).toBeNull();
  // Delete waits on the only criterion.
  act(() => rows[0].querySelector<HTMLButtonElement>(".action-menu-button")!.click());
  const deleteItem = [...step.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((item) => item.textContent === "Delete")!;
  expect(deleteItem.getAttribute("aria-disabled")).toBe("true");
  expect(document.getElementById(deleteItem.getAttribute("aria-describedby")!)!.textContent).toBe("A project needs at least one criterion.");
  act(() => deleteItem.click());
  // Add criterion sits under the list, with no chain line (a chain is of two or more).
  const addLink = buttonIn(step, "Add criterion");
  expect(addLink.classList.contains("link-button")).toBe(true);
  expect(rows[0].closest(".criterion-list")!.compareDocumentPosition(addLink) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(step.querySelector(".criterion-panel")).toBeNull();                          // the list shows no panel
  expect(step.textContent).not.toContain("Add another criterion");
  expect(step.querySelector(".chain-summary")).toBeNull();
  showCriterionEditor();
  openPanelSection("Test surfaces");
  expect(surfaceSetSwitches()).toEqual([["surfaces.obj", true]]);
  expect(buttonIn(pinnedBar(), "Build envelope and massing")).toBeDefined();
  expect(stepRow("Criteria").querySelector(".step-summary")).toBeNull();               // open, no setting to fix
  openStep("Site");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Sun hours, 61 % kept");
});

test("the criteria step pins the build, and Run analysis while the analysis is out of date; Site has neither", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  expect(buttonIn(pinnedBar(), "Run analysis")).toBeUndefined();
  expect(buttonIn(pinnedBar(), "Build envelope and massing").disabled).toBe(false);
  service.stages = { ...CARVED, preprocessing: "out_of_date" };
  await act(async () => window.dispatchEvent(new Event("focus")));         // the stage status is read again
  await settle();
  expect(buttonIn(pinnedBar(), "Run analysis").disabled).toBe(false);
  openStep("Site");
  expect(buttonIn(container(), "Run analysis")).toBeUndefined();                                                   // only for Criteria
  expect(buttonIn(container(), "Build envelope and massing")).toBeUndefined();
});

test("build waits in the pinned bar until every criterion is carved", async () => {
  // Never analysed: the build waits for the first analysis.
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  const neverAnalysed = buttonIn(pinnedBar(), "Build envelope and massing");
  expect(buttonIn(pinnedBar(), "Run analysis").disabled).toBe(false);            // nothing blocks the run: the build's own reason shows
  expect(neverAnalysed.disabled).toBe(true);
  expect(reasonOf(neverAnalysed)).toBe("Run the analysis before building");
  expect(pinnedBar().querySelectorAll(".run-button-reason")).toHaveLength(1);    // under the build only
  expect(neverAnalysed.closest(".run-button-area")!.querySelector(".run-button-reason")).not.toBeNull();
  unmountWorkspace();
  // The analysis is current but the carving is not: it waits for the carving.
  const analysed: Record<PipelineStage, StageState> = { ...CARVED, thresholding: "out_of_date" };
  service = new FakeService(analysed, CARVING);
  await openWorkspace(service, project(analysed));
  openStep("Criteria");
  const build = () => buttonIn(pinnedBar(), "Build envelope and massing");
  expect(build().disabled).toBe(true);
  expect(reasonOf(build())).toBe("Update the carving before building");
  unmountWorkspace();
  // The settings shown differ from the analysis: its existing reason.
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  type(voxelSizeField(), "2");
  closeProjectSettings();
  openStep("Criteria");
  expect(reasonOf(build())).toBe("Settings changed: run the analysis again before building");
});

test("during a run the criterion's controls are disabled and the pinned bar says why once, under both buttons", async () => {
  const analysisOutOfDate: Record<PipelineStage, StageState> = { ...CARVED, preprocessing: "out_of_date" };
  service = new FakeService(analysisOutOfDate, CARVING);
  await openWorkspace(service, project(analysisOutOfDate, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  await pressRunAnalysis();
  expect(service.runsStarted).toHaveLength(1);
  const runButton = buttonIn(pinnedBar(), "Run analysis");
  expect(reasonOf(runButton)).toBe("A run is in progress");
  expect(reasonOf(buttonIn(pinnedBar(), "Build envelope and massing"))).toBe("A run is in progress");      // the same line
  expect(pinnedBar().textContent!.split("A run is in progress")).toHaveLength(2);
  expect(panel()!.textContent).not.toContain("A run is in progress");
  openPanelSection("Test surfaces");
  expect(setSwitch("surfaces.obj").disabled).toBe(true);
  openStep("Site");
  expect(surfaceSetsBox()!.querySelector<HTMLButtonElement>(".input-add")!.disabled).toBe(true);
});

test("an earlier project shows its test surfaces in the criterion", async () => {
  const opened: ProjectDetail = {
    ...project(EVERY_STAGE_CURRENT),
    inputs: { max_volume: [{ name: "volume.obj", triangle_count: 1 }], test_surfaces: [{ name: "roofs.ply", triangle_count: 20 }, { name: "windows.ply", triangle_count: 8 }],
              weather: [{ name: "weather.epw", triangle_count: 0 }] },
    criteria: [criterionEntry({ mode: "time-based" }, ["roofs.ply", "windows.ply"])],
    criterion_status: { 1: EVERY_STAGE_CURRENT },
  };
  service = new FakeService(EVERY_STAGE_CURRENT, CARVING);
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: MASSING };
  await openWorkspace(service, opened);
  openStep("Criteria");
  openPanelSection("Test surfaces");
  expect(surfaceSetSwitches()).toEqual([["roofs.ply", true], ["windows.ply", true]]);
  expect(setSwitches().querySelector(".input-file-detail")!.textContent).toBe("20 triangles");
  for (const title of ["Site", "Criteria", "Envelope and massing", "Export"]) {
    expect(stepRow(title).querySelector(".step-mark-done"), title).not.toBeNull();
  }
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);      // the 3D view still draws them
});

test("the Site step holds the site's geometry, then the project's test surfaces; the weather file is first in Location in the project settings", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  const titles = [...stepRow("Site").querySelectorAll(".input-box h3")].map((title) => title.textContent);
  expect(titles).toEqual(["Context", "Test surfaces", "Terrain", "Maximum volume"]);   // what is around the site first
  expect(setNamesIn(surfaceSetsBox()!)).toEqual(["surfaces.obj"]);
  openProjectSettings();
  const location = projectSettings()!.querySelector(".setting-group-essential")!;
  expect(location.parentElement!.querySelector(".setting-group-title")!.textContent).toBe("Location");
  expect([...location.children].map((child) => child.getAttribute("data-setting"))).toEqual(["weather_file", "north_deg"]);
  expect(location.querySelector('[data-setting="weather_file"] h3')!.textContent).toBe("Weather file");
  closeProjectSettings();
  expect(stepRow("Site").querySelector(".step-mark-done")).not.toBeNull();         // the maximum volume is there
});

test("the project settings show only shared settings, and no run button", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { north_deg: 10, voxel_size: 0.5 }));
  expect(settingsButton().title).toBe("Golden, CO, USA. North 10°, 0.5\u00a0m voxels. Opens the settings every criterion shares.");
  openProjectSettings();
  const inWindow = (setting: string) => projectSettings()!.querySelector(`[data-setting="${setting}"]`);
  expect(inWindow("voxel_size")).not.toBeNull();
  expect(inWindow("start_month")).toBeNull();
  expect(buttonIn(projectSettings()!, "Run analysis")).toBeUndefined();
  closeProjectSettings();
  openStep("Criteria");
  openPanelSection("Settings");
  expect(field("start_month")).not.toBeNull();
  expect(field("voxel_size")).toBeNull();
});

test("a criterion of a project without test surfaces says where to add them, and its link opens the Site step", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, { ...project(NOTHING_RUN, { mode: "daylight" }), inputs: { ...project(NOTHING_RUN).inputs, test_surfaces: [] },
                                 criteria: [criterionEntry({ mode: "daylight" }, [])] });
  openStep("Criteria");
  expect(setSwitches().querySelector(".input-box-hint")!.textContent).toBe("Windows or facades that need daylight. Flat panels; a curved or folded one is skipped.");
  expect(setSwitches().querySelector(".surface-set-note")!.textContent).toContain("The project has no test surfaces yet.");
  const runButton = buttonIn(pinnedBar(), "Run analysis");
  expect(runButton.disabled).toBe(true);
  expect(reasonOf(runButton)).toBe("Choose test surfaces to run the analysis");
  act(() => buttonIn(setSwitches(), "Open the Site step").click());
  expect(stepIsOpen("Site")).toBe(true);
  expect(surfaceSetsBox()!.classList.contains("input-box-empty")).toBe(true);
});

test("a criterion that uses none of the project's sets shows them switched off, and Run analysis waits", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, { ...project(NOTHING_RUN), inputs: { ...project(NOTHING_RUN).inputs, test_surfaces: [{ name: "surfaces.obj", triangle_count: 1, used_by: [] }] },
                                 criteria: [criterionEntry({ mode: "time-based" }, [])] });
  openStep("Criteria");
  expect(surfaceSetSwitches()).toEqual([["surfaces.obj", false]]);
  expect(setSwitches().querySelector(".surface-set-note")).toBeNull();
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Choose test surfaces to run the analysis");
});

test("test surfaces added in the Site step go to the project's routes and are used by no criterion until switched on", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  const statusReadsBefore = service.count("GET /stage-status");
  const picker = surfaceSetsBox()!.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(picker, "files", { value: [new File([TRIANGLE_OBJ], "windows.obj")], configurable: true });
  act(() => picker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  expect(service.requests).toContain("POST /inputs/test_surfaces");
  expect(service.requests.some((request) => request.startsWith("POST /criteria/") || request.startsWith("PUT /criteria/"))).toBe(false);
  expect(setNamesIn(surfaceSetsBox()!)).toEqual(["surfaces.obj", "windows.obj"]);
  expect(service.count("GET /inputs/test_surfaces/windows.obj")).toBe(1);             // the 3D view draws the new set
  expect(service.count("GET /stage-status")).toBe(statusReadsBefore + 1);
  // The set the criterion uses cannot be removed; the new one can
  const removeSurfaces = surfaceSetsBox()!.querySelector<HTMLButtonElement>('[aria-label="Remove surfaces.obj"]')!;
  expect(removeSurfaces.disabled).toBe(true);
  expect(removeSurfaces.title.split("\n")).toEqual(["Used by time-based: switch it off there to remove it", "1 triangle"]);
  expect(surfaceSetsBox()!.textContent).not.toContain("Used by time-based");     // said in the remove button's title, not in the row
  openStep("Criteria");
  openPanelSection("Test surfaces");
  expect(surfaceSetSwitches()).toEqual([["surfaces.obj", true], ["windows.obj", false]]);
  openStep("Site");
  await act(async () => surfaceSetsBox()!.querySelector<HTMLButtonElement>('[aria-label="Remove windows.obj"]')!.click());
  await settle();
  expect(service.requests).toContain("DELETE /inputs/test_surfaces/windows.obj");
  expect(service.requests.some((request) => request.startsWith("DELETE /criteria/"))).toBe(false);
  expect(setNamesIn(surfaceSetsBox()!)).toEqual(["surfaces.obj"]);
  expect(service.count("GET /stage-status")).toBe(statusReadsBefore + 2);
});

test("a criterion's switch puts a set on or takes it off through the criterion's routes; the stored files and the stage status follow", async () => {
  service = new FakeService(CARVED, CARVING);
  const opened = project(CARVED);
  await openWorkspace(service, { ...opened, inputs: { ...opened.inputs, test_surfaces: [...opened.inputs.test_surfaces!, { name: "windows.obj", triangle_count: 1, used_by: [] }] } });
  openStep("Criteria");
  const statusReadsBefore = service.count("GET /stage-status");
  const storedReadsBefore = service.count("GET /inputs/test_surfaces");
  openPanelSection("Test surfaces");
  service.stages = { ...CARVED, preprocessing: "out_of_date", thresholding: "out_of_date" };
  await act(async () => setSwitch("windows.obj").click());
  await settle();
  expect(service.requests).toContain("PUT /criteria/1/test-surfaces/windows.obj");
  expect(service.count("GET /inputs/test_surfaces")).toBe(storedReadsBefore + 1);     // the sets read again, for who uses them
  expect(surfaceSetSwitches()).toEqual([["surfaces.obj", true], ["windows.obj", true]]);
  expect(service.count("GET /stage-status")).toBe(statusReadsBefore + 1);
  expect(buttonIn(pinnedBar(), "Build envelope and massing").disabled).toBe(true);   // the carving is out of date: nothing to build from

  await act(async () => setSwitch("surfaces.obj").click());
  await settle();
  expect(service.requests).toContain("DELETE /criteria/1/test-surfaces/surfaces.obj");
  expect(service.requests.some((request) => request.startsWith("DELETE /inputs/"))).toBe(false);
  expect(surfaceSetSwitches()).toEqual([["surfaces.obj", false], ["windows.obj", true]]);       // the set stays in the project
  expect(service.count("GET /stage-status")).toBe(statusReadsBefore + 2);
  openStep("Site");
  expect(surfaceSetsBox()!.querySelector<HTMLButtonElement>('[aria-label="Remove surfaces.obj"]')!.disabled).toBe(false);
  expect(surfaceSetsBox()!.querySelector<HTMLButtonElement>('[aria-label="Remove windows.obj"]')!.disabled).toBe(true);
});

// ---- What the Criteria step shows: the list or the editor of one criterion ----

const editorName = () => container().querySelector(".criterion-editor-name")?.textContent ?? null;
const listShown = () => container().querySelector(".criterion-list") !== null;

test("a project with one criterion opens the Criteria step on its editor; with two, on the list", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  expect(editorName()).not.toBeNull();
  expect(listShown()).toBe(false);
  unmountWorkspace();
  await openChain([FACADES, WINDOWS]);
  expect(listShown()).toBe(true);
  expect(editorName()).toBeNull();
});

test("after All criteria, closing and opening the Criteria step shows the list again", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  expect(listShown()).toBe(false);
  showCriterionCards();
  openStep("Site");
  openStep("Criteria");
  expect(listShown()).toBe(true);                        // remembered, not decided again from the one criterion
  unmountWorkspace();
  await openChain([FACADES, WINDOWS]);
  showCriterionEditor();
  openStep("Site");
  openStep("Criteria");
  expect(editorName()).toBe("Winter sun on facades");     // and the editor too, of two criteria
});

test("a run that ends and opens the Criteria step keeps the list or the editor as it was", async () => {
  // Run analysis is pinned under Criteria: the step is closed first, so the end of the run opens it again.
  async function runFromCriteria() {
    openStep("Site");
    await pressRunAnalysis();
    service.stages = CARVED;
    FakeWebSocket.opened.at(-1)!.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
    await settle();
    expect(stepIsOpen("Criteria")).toBe(true);
  }
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  showCriterionCards();
  await runFromCriteria();
  expect(listShown()).toBe(true);
  unmountWorkspace();
  FakeWebSocket.opened = [];
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  expect(editorName()).not.toBeNull();
  await runFromCriteria();
  expect(listShown()).toBe(false);
  expect(editorName()).not.toBeNull();
});

test("a run failure's link to a criterion setting opens the editor of that criterion with the field focused", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid",
                                 field_errors: [{ field: "max_slope_deg", message: "Input should be less than 90" }] });
  await settle();
  showCriterionCards();
  expect(listShown()).toBe(true);
  act(() => buttonIn(container(), "Go to steepest slope of the envelope").click());
  expect(listShown()).toBe(false);
  const slopeField = container().querySelector('[data-setting="max_slope_deg"]')!;
  expect(slopeField.contains(document.activeElement)).toBe(true);       // the field, not the editor's name, has the focus
  expect(document.activeElement).not.toBe(container().querySelector(".criterion-editor-name"));
});

test("a new weather file's notice opens the Criteria step on the criterion it concerns, its notice under the Settings header", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = { location: "Brisbane, AUS", latitude: -27.38 };
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  showCriterionCards();
  openStep("Site");
  await addWeatherFileInSettings();
  openStep("Criteria");
  expect(listShown()).toBe(false);
  expect(editorName()).not.toBeNull();
  openPanelSection("Settings");
  const notice = container().querySelector<HTMLElement>(".weather-change-notice")!;
  expect(notice.textContent).toContain("Brisbane, AUS");
  const settingsSection = [...container().querySelectorAll<HTMLElement>(".panel-section")]
    .find((section) => section.querySelector(".panel-section-title")!.textContent === "Settings")!;
  expect(settingsSection.contains(notice)).toBe(true);
});

test("deleting criteria down to one leaves the step on the list", async () => {
  await openChain([FACADES, WINDOWS, ROOFS]);
  await deleteCriterion("Daylight on roofs");
  await deleteCriterion("Spring sun on windows");
  expect(container().querySelectorAll(".criterion-card")).toHaveLength(1);
  expect(listShown()).toBe(true);
  expect(editorName()).toBeNull();
});

test("the workspace made again after a rename opens on the same criterion, in the editor (Review Focus 3)", async () => {
  const stepsReported = vi.fn();
  await openChain([FACADES, WINDOWS], undefined, () => {}, [], (opened) => opened,
                  { startSteps: { open: "criteria", view: "criteria", criteria: { shows: "editor", criterionId: "2" } }, onStepsChange: stepsReported });
  await settle();
  openStep("Criteria");                                  // openChain pressed the open step shut
  await settle();
  expect(editorName()).toBe("Spring sun on windows");
  expect(listShown()).toBe(false);
  expect(container().querySelector(".criterion-panel")).not.toBeNull();       // its settings are in
  expect(stepsReported).toHaveBeenLastCalledWith({ open: "criteria", view: "criteria", criteria: { shows: "editor", criterionId: "2" } });
});

test("the steps reported name the criterion pressed while its settings are on their way, so a rename then reopens on it", async () => {
  const stepsReported = vi.fn();
  await openChain([FACADES, WINDOWS], undefined, () => {}, [], (opened) => opened, { onStepsChange: stepsReported });
  chainService.settingsAnswerWhen["2"] = new Promise(() => {});        // its settings never come in this test
  await select("Spring sun on windows");
  expect(container().querySelector('.criterion-panel-frame [role="status"]')!.textContent).toBe("Loading the settings of Spring sun on windows");
  expect(stepsReported).toHaveBeenLastCalledWith(expect.objectContaining({ criteria: { shows: "editor", criterionId: "2" } }));
});
