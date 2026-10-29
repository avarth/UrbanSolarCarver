// The open project's steps for one criterion, against a fake service: Inputs hold the site, Site and grid the shared settings,
// and Criteria opens straight on the criterion, whose test surfaces go through its own routes. The last tests are of what the
// Criteria step shows, the list or the editor of one criterion: how it opens, what it keeps, and what leads to a criterion's settings.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ProjectDetail } from "../api_client/client";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import type { PipelineStage, StageState } from "./step_summaries";
import { FACADES, ROOFS, WINDOWS, deleteCriterion, openChain, select, service as chainService } from "./chain_service_for_test";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, NOTHING_RUN, TRIANGLE_OBJ, buttonIn, container, criterionEntry, endWorkspaceTest, openStep,
  openPanelSection, openWorkspace, pinnedBar, pressRunAnalysis, project, reasonOf, settle, showCriterionCards, showCriterionEditor, startWorkspaceTest, stepRow, type,
  unmountWorkspace, voxelSizeField,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let service: FakeService;
beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

const EVERY_STAGE_CURRENT: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
const panel = () => container().querySelector<HTMLElement>(".criterion-panel");
const protectsBox = () => panel()!.querySelector<HTMLElement>(".input-box")!;
const protectedFiles = () => [...protectsBox().querySelectorAll(".input-file-name")].map((name) => name.textContent);
const field = (setting: string) => container().querySelector(`[data-setting="${setting}"]`);
const stepTitles = () => [...container().querySelectorAll(".step-title")].map((title) => title.textContent);

test("the steps are Inputs, Site and grid, Criteria, Envelope and massing and Export", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  expect(stepTitles()).toEqual(["Inputs", "Site and grid", "Criteria", "Envelope and massing", "Export"]);
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
  expect(protectedFiles()).toEqual(["surfaces.obj"]);
  expect(buttonIn(pinnedBar(), "Run analysis")).toBeDefined();
  expect(buttonIn(pinnedBar(), "Build envelope and massing")).toBeDefined();
  expect(stepRow("Criteria").querySelector(".step-summary")).toBeNull();               // open, no setting to fix
  openStep("Inputs");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Solar time-based, 61 % kept");
});

test("a new project opens with one criterion in the list, its switch on", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  showCriterionCards();
  const rows = [...stepRow("Criteria").querySelectorAll(".criterion-list .criterion-card")];
  expect(rows).toHaveLength(1);
  expect(rows[0].querySelector<HTMLInputElement>('[role="switch"]')!.checked).toBe(true);
  expect(rows[0].querySelector(".criterion-card-line")!.textContent).not.toBe("Off");
});

test("the criteria step pins run analysis and build side by side under the steps", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  const bar = pinnedBar();
  const run = buttonIn(bar, "Run analysis"), build = buttonIn(bar, "Build envelope and massing");
  expect(run.disabled).toBe(false);
  expect(build.disabled).toBe(false);
  expect(run.closest(".run-button-area")!.parentElement).toBe(build.closest(".run-button-area")!.parentElement);      // one row
  expect(stepRow("Criteria").contains(bar)).toBe(false);                                                             // under the step list
  expect(bar.compareDocumentPosition(panel()!) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  openStep("Inputs");
  expect(container().querySelector(".step-pinned-action")).toBeNull();                                               // only for Criteria
});

test("the panel has no run analysis of its own", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  for (const section of ["Test surfaces", "Mode", "Settings", "Carving rule"]) openPanelSection(section);
  expect([...panel()!.querySelectorAll("button")].map((button) => button.textContent)).not.toContain("Run analysis");
  expect(panel()!.querySelector(".criterion-run")).toBeNull();
  expect(panel()!.querySelector(".run-button-area")).toBeNull();
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
  // The analysis is current but the carving is not: it waits for the carving.
  const analysed: Record<PipelineStage, StageState> = { ...CARVED, thresholding: "out_of_date" };
  service = new FakeService(analysed, CARVING);
  await openWorkspace(service, project(analysed));
  openStep("Criteria");
  const build = () => buttonIn(pinnedBar(), "Build envelope and massing");
  expect(build().disabled).toBe(true);
  expect(reasonOf(build())).toBe("Update the carving before building");
  // The settings shown differ from the analysis: its existing reason.
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Site and grid");
  type(voxelSizeField(), "2");
  openStep("Criteria");
  expect(reasonOf(build())).toBe("Settings changed: run the analysis again before building");
});

test("during a run the criterion's controls are disabled and the pinned bar says why once, under both buttons", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  await pressRunAnalysis();
  expect(service.runsStarted).toHaveLength(1);
  const runButton = buttonIn(pinnedBar(), "Run analysis");
  expect(reasonOf(runButton)).toBe("A run is in progress");
  expect(reasonOf(buttonIn(pinnedBar(), "Build envelope and massing"))).toBe("A run is in progress");      // the same line
  expect(pinnedBar().textContent!.split("A run is in progress")).toHaveLength(2);
  expect(panel()!.textContent).not.toContain("A run is in progress");
  openPanelSection("Test surfaces");
  expect(protectsBox().querySelector<HTMLButtonElement>(".input-add")!.disabled).toBe(true);
  openPanelSection("Mode");
  expect(panel()!.querySelector('[role="radiogroup"]')!.getAttribute("aria-disabled")).toBe("true");
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
  expect(protectedFiles()).toEqual(["roofs.ply", "windows.ply"]);
  expect(protectsBox().querySelector(".input-file-detail")!.textContent).toBe("20 triangles");
  for (const title of ["Inputs", "Site and grid", "Criteria", "Envelope and massing", "Export"]) {
    expect(stepRow(title).querySelector(".step-mark-done"), title).not.toBeNull();
  }
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);      // the 3D view still draws them
});

test("inputs hold only the site", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  const titles = [...stepRow("Inputs").querySelectorAll(".input-box h3")].map((title) => title.textContent);
  expect(titles).toEqual(["Maximum volume", "Existing surroundings (optional)", "Terrain (optional)", "Weather file (optional)"]);
  expect(stepRow("Inputs").querySelector(".step-mark-done")).not.toBeNull();         // the maximum volume is there
});

test("site and grid shows only shared settings", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { north_deg: 10, voxel_size: 0.5 }));
  expect(stepRow("Site and grid").querySelector(".step-summary")!.textContent).toBe("North 10°, 0.5 m voxels");
  openStep("Site and grid");
  expect(field("voxel_size")).not.toBeNull();
  expect(field("start_month")).toBeNull();
  expect(buttonIn(container().querySelector(".step-pinned-action")!, "Run analysis")).toBeDefined();
  openStep("Criteria");
  openPanelSection("Settings");
  expect(field("start_month")).not.toBeNull();
  expect(field("voxel_size")).toBeNull();
});

test("a criterion without test surfaces says what to add", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, { ...project(NOTHING_RUN, { mode: "daylight" }), inputs: { ...project(NOTHING_RUN).inputs, test_surfaces: [] },
                                 criteria: [criterionEntry({ mode: "daylight" }, [])] });
  openStep("Criteria");
  expect(protectsBox().querySelector(".input-box-hint")!.textContent).toBe("Windows or facades that need daylight.");
  expect(buttonIn(protectsBox(), "Add test surfaces")).toBeDefined();
  const runButton = buttonIn(pinnedBar(), "Run analysis");
  expect(runButton.disabled).toBe(true);
  expect(reasonOf(runButton)).toBe("Add test surfaces to run the analysis");
});

test("test surfaces added to and removed from the criterion go to its routes; the stored files and the stage status follow", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  const statusReadsBefore = service.count("GET /stage-status");
  openPanelSection("Test surfaces");
  const picker = protectsBox().querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(picker, "files", { value: [new File([TRIANGLE_OBJ], "windows.obj")], configurable: true });
  service.stages = { ...CARVED, preprocessing: "out_of_date", thresholding: "out_of_date" };
  act(() => picker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  expect(service.requests).toContain("POST /criteria/1/test-surfaces");
  expect(service.requests.some((request) => request.startsWith("POST /inputs/"))).toBe(false);
  expect(service.requests).toContain("GET /inputs/test_surfaces");
  expect(protectedFiles()).toEqual(["surfaces.obj", "windows.obj"]);
  const fileReads = (fileName: string) => service.count(`GET /inputs/test_surfaces/${fileName}`);
  expect(fileReads("windows.obj")).toBe(1);                                          // the 3D view draws the new file
  expect(service.count("GET /stage-status")).toBe(statusReadsBefore + 1);
  expect(buttonIn(pinnedBar(), "Build envelope and massing").disabled).toBe(true);   // the carving is out of date: nothing to build from

  await act(async () => protectsBox().querySelector<HTMLButtonElement>('[aria-label="Remove surfaces.obj"]')!.click());
  await settle();
  expect(service.requests).toContain("DELETE /criteria/1/test-surfaces/surfaces.obj");
  expect(service.requests.some((request) => request.startsWith("DELETE /inputs/"))).toBe(false);
  expect(protectedFiles()).toEqual(["windows.obj"]);
  expect(service.count("GET /stage-status")).toBe(statusReadsBefore + 2);
  expect(fileReads("windows.obj")).toBe(2);                                          // the test surfaces drawn again, without the removed file
  expect(fileReads("surfaces.obj")).toBe(2);                                         // drawn at the start and after the upload only
});

// ---- What the Criteria step shows: the list or the editor of one criterion ----

const editorName = () => container().querySelector(".criterion-editor-name")?.textContent ?? null;
const listShown = () => container().querySelector(".criterion-list") !== null;
const REFUSED_FOR_TEST_SURFACES = "Add test surfaces to Spring sun on windows.";

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
  openStep("Inputs");
  openStep("Criteria");
  expect(listShown()).toBe(true);                        // remembered, not decided again from the one criterion
  unmountWorkspace();
  await openChain([FACADES, WINDOWS]);
  showCriterionEditor();
  openStep("Inputs");
  openStep("Criteria");
  expect(editorName()).toBe("Winter sun on facades");     // and the editor too, of two criteria
});

test("a run that ends and opens the Criteria step keeps the list or the editor as it was", async () => {
  async function runFromSiteAndGrid() {
    openStep("Site and grid");
    await pressRunAnalysis();
    service.stages = CARVED;
    FakeWebSocket.opened.at(-1)!.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
    await settle();
    expect(stepRow("Criteria").classList.contains("step-open")).toBe(true);
  }
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  showCriterionCards();
  await runFromSiteAndGrid();
  expect(listShown()).toBe(true);
  unmountWorkspace();
  FakeWebSocket.opened = [];
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  expect(editorName()).not.toBeNull();
  await runFromSiteAndGrid();
  expect(listShown()).toBe(false);
  expect(editorName()).not.toBeNull();
});

test("a run refused because a criterion has no test surfaces opens that criterion's editor, from Site and grid and from the Criteria bar", async () => {
  await openChain([FACADES, WINDOWS]);
  chainService.runRefusal = { status: 422, body: { detail: REFUSED_FOR_TEST_SURFACES, missing_inputs: ["test_surfaces:2"] } };
  expect(listShown()).toBe(true);
  await pressRunAnalysis();                              // the Criteria bar's: it says the reason under its button
  expect(editorName()).toBe("Spring sun on windows");
  expect(pinnedBar().querySelector(".run-outcome-error")!.textContent).toBe(REFUSED_FOR_TEST_SURFACES);
  expect(container().querySelector(".criterion-panel-problem")).toBeNull();
  await select("Winter sun on facades");
  showCriterionCards();
  openStep("Site and grid");
  await pressRunAnalysis();                              // Site and grid's own button
  openStep("Criteria");
  expect(editorName()).toBe("Spring sun on windows");
  expect(container().querySelector(".criterion-panel-problem")!.textContent).toBe(REFUSED_FOR_TEST_SURFACES);
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
  act(() => buttonIn(container(), "Go to steepest step between columns").click());
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
  openStep("Inputs");
  const weatherPicker = container().querySelector<HTMLInputElement>('input[type="file"][accept=".epw"]')!;
  Object.defineProperty(weatherPicker, "files", { value: [new File(["LOCATION"], "weather.epw")], configurable: true });
  act(() => weatherPicker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
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
