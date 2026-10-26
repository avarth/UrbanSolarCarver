// The open project's steps for one criterion, against a fake service: Inputs hold the site, Site and grid the shared settings,
// and Criteria opens straight on the criterion, whose test surfaces go through its own routes.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ProjectDetail } from "../api_client/client";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import type { PipelineStage, StageState } from "./step_summaries";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, NOTHING_RUN, TRIANGLE_OBJ, buttonIn, container, criterionEntry, endWorkspaceTest, openStep,
  openPanelSection, openWorkspace, pinnedBar, pressRunAnalysis, project, reasonOf, settle, startWorkspaceTest, stepRow, type, voxelSizeField,
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
  expect(addLink.compareDocumentPosition(panel()!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(step.textContent).not.toContain("Add another criterion");
  expect(step.querySelector(".chain-summary")).toBeNull();
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
  expect(buttonIn(pinnedBar(), "Build envelope and massing").disabled).toBe(true);
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
  expect(reasonOf(build())).toBe("Settings changed since the analysis. Run the analysis again before building.");
});

test("during a run the criterion's controls are disabled and the panel says why once, at Run analysis", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  await pressRunAnalysis();
  expect(service.runsStarted).toHaveLength(1);
  const runButton = buttonIn(pinnedBar(), "Run analysis");
  expect(reasonOf(runButton)).toBe("A run is in progress");
  expect(panel()!.textContent).not.toContain("A run is in progress");
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
