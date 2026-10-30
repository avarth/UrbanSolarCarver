// The open project as a whole, against a fake service: settings saves, the run loop, the stage status and the locks and
// build buttons that follow from them, as the unit tests of each cannot show them together.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { addStyleSheetForTest } from "../viewer_overlays/render_for_test";
import type { ModeInfo, ProjectDetail } from "../api_client/client";
import { LAYERS_SHOWN_IN_STEP, type OpenProjectSettingsSaver } from "./ProjectWorkspace";
import type { PipelineStage, StageState } from "./step_summaries";
import {
  CURRENT, FACADES, OUT_OF_DATE, ROOFS, WINDOWS, card, cardLine, carvingSummaryOf, openChain, panel, panelFrame, select, selectedCardName,
  service as chainService,
  type CriterionStages,
} from "./chain_service_for_test";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, MODES, NOTHING_RUN, SCHEMA, TRIANGLE_OBJ, buildPart, buttonIn, container,
  dimmedCarvingLayers, endWorkspaceTest, openPanelSection, openStep, openWorkspace, panelSectionOpen, pinnedBar, pressRunAnalysis, project, reasonOf, settle,
  showCriterionEditor, startWorkspaceTest, stepRow, thresholdField, thresholdOf, togglePanelSection, type, typeAndLeave, unmountWorkspace, voxelSizeField,
  waitForTheSave,
} from "./project_workspace_for_test";

vi.mock("../viewer/scene", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../viewer/scene")>()), ViewerScene: (await import("../viewer/fake_scene_for_test")).FakeViewerScene,
}));

let service: FakeService;
beforeEach(startWorkspaceTest);
afterEach(endWorkspaceTest);

test("a settings change saves; Run analysis starts a run; its events finish it; the stage status and the summary are fetched; the carving undims", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  expect(service.count("GET /run/summary")).toBe(0);           // nothing has run: no results to fetch
  openStep("Site and grid");

  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ voxel_size: 2 }]);
  expect(service.count("GET /stage-status")).toBe(1);           // the save changed what the stages ran with

  await pressRunAnalysis();
  expect(service.runsStarted).toEqual([["thresholding"]]);
  expect(FakeWebSocket.opened).toHaveLength(1);
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels", "sky_dome"]);     // the run brings them

  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "preprocessing", done: 0, total: 1 });
  run.send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  await settle();
  service.stages = CARVED;
  service.summary = { carving: CARVING, envelope: null, massing: null };
  run.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();

  expect(service.count("GET /run/summary")).toBe(1);
  expect(service.count("GET /stage-status")).toBe(2);
  expect(stepRow("Criteria").classList.contains("step-open")).toBe(true);    // a finished analysis opens Criteria
  expect(stepRow("Criteria").textContent).toContain("Kept here61 %of what reached this criterion");
  expect(dimmedCarvingLayers()).toEqual([]);
  openStep("Site and grid");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Solar time-based, 61\u00a0% kept");
});

test("a save the service refuses keeps Run analysis from starting a run, and says why", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.refuseSavesWith = 409;
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Site and grid");

  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  const notice = () => container().querySelector(".save-failure");
  expect(notice()!.textContent).toContain("The last change to the settings was not saved.");
  expect(notice()!.textContent).toContain("A run of this project is in progress, perhaps in another tab. Save again once it has ended.");

  await pressRunAnalysis();
  expect(service.count("PUT /shared-settings")).toBe(2);       // Run analysis sent the change again first
  expect(service.runsStarted).toEqual([]);
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(notice()).not.toBeNull();
});

// The shared settings are saved with PUT shared-settings, the settings of the criterion (the mode among them) with PATCH criteria/1.
const settingsSaves = () => service.requests.filter((request) => request.startsWith("PUT") || request.startsWith("PATCH"));
const modeTiles = () => [...container().querySelectorAll<HTMLElement>('[role="radio"]')];
const siteAndGridSummaryText = () => stepRow("Site and grid").querySelector(".step-summary")!.textContent;
/** The text of the criterion's period field, its Settings section opened first. */
function periodFieldText() {
  openPanelSection("Settings");
  return container().querySelector('[data-setting="start_month"]')!.textContent;
}

test("saving the voxel size sends only shared settings", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { start_month: 3, north_deg: 10 }));
  openStep("Site and grid");
  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PUT /shared-settings"]);
  expect(service.savedValues).toEqual([{ north_deg: 10, voxel_size: 2 }]);     // no mode, no setting of the criterion
});

test("saving the analysis period sends the criterion's settings", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { voxel_size: 2, threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  openPanelSection("Settings");
  act(() => buttonIn(container(), "21 June").click());
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect(service.savedValues).toEqual([{ mode: "time-based", start_month: 6, end_month: 6, threshold: { method: "cutoff", value: 1.5 } }]);
  expect(service.count("GET /stage-status")).toBe(1);           // the save changed what the analysis reads
});

test("a rejected criterion setting marks its field", async () => {
  service = new FakeService(CARVED, CARVING);
  service.configErrorsOf = (values) => (values.max_slope_deg === 100 ? [{ field: "max_slope_deg", message: "Input should be less than 90" }] : null);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  act(() => stepRow("Criteria").querySelector<HTMLButtonElement>(".carving-settings .setting-fold")!.click());      // More carving settings
  typeAndLeave(container().querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="number"]')!, "100");
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect(service.savedValues).toEqual([]);
  expect(container().querySelector('[data-setting="max_slope_deg"] .setting-error')!.textContent).toBe("Input should be less than 90");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("1 setting to fix");
  expect(service.count("POST /runs")).toBe(0);
});

test("a mode change starts the criterion from the new mode's values", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { voxel_size: 2, start_month: 3 }));
  openStep("Criteria");
  expect(periodFieldText()).toContain("21 Mar");
  openPanelSection("Mode");
  act(() => modeTiles()[4].click());                                  // Daylight
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect(service.savedValues).toEqual([{ mode: "daylight" }]);         // not the period of Solar time-based, nor the shared voxel size
  act(() => modeTiles()[1].click());                                  // Solar time-based again: its own period, not the one set before
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1", "PATCH /criteria/1"]);
  expect(service.savedValues.at(-1)).toEqual({ mode: "time-based" });
  expect(periodFieldText()).toContain("21 Dec");
  expect(siteAndGridSummaryText()).toContain("2\u00a0m");          // the shared voxel size stays
});

test("a shared change refused for the criterion's mode is saved again once a mode change makes it storable, and Run analysis starts", async () => {
  service = new FakeService(NOTHING_RUN, null);
  // The service checks the shared settings with the criterion: Solar time-based needs the weather file the project lacks.
  service.configErrorsOf = (values) => ("voxel_size" in values && service.criterionSettings.mode === "time-based"
    ? [{ field: null, message: "Value error, mode 'time-based' requires epw_path" }] : null);
  await openWorkspace(service, { ...project(NOTHING_RUN), inputs: { ...project(NOTHING_RUN).inputs, weather: [] }, weather_location: null, weather_latitude: null });
  openStep("Site and grid");
  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PUT /shared-settings"]);
  expect(container().querySelector(".step-error")!.textContent).toBe("Add a weather file to run this mode");

  openStep("Criteria");
  act(() => modeTiles()[4].click());                                  // Daylight reads no weather file
  await waitForTheSave();
  await settle();
  await waitForTheSave();                                             // the shared settings, sent again after the criterion's save
  await settle();
  expect(settingsSaves()).toEqual(["PUT /shared-settings", "PATCH /criteria/1", "PUT /shared-settings"]);
  expect(service.savedValues).toEqual([{ mode: "daylight" }, { voxel_size: 2 }]);
  openStep("Site and grid");
  expect(container().querySelector(".step-error")).toBeNull();
  await pressRunAnalysis();
  expect(service.runsStarted).toEqual([["thresholding"]]);
});

test("a page opened during a run it does not follow: Run analysis answered with up to date brings the carving the service holds", async () => {
  service = new FakeService(CARVED, CARVING);                  // the run has ended since
  service.everythingUpToDate = true;
  await openWorkspace(service, project(NOTHING_RUN));                   // opened while the run had removed the stage records
  openStep("Site and grid");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Solar time-based, Not run yet");

  await pressRunAnalysis();
  expect(container().querySelector(".step-pinned-action")!.textContent).toContain("Results are up to date");
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(service.count("GET /run/summary")).toBe(1);
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Solar time-based, 61\u00a0% kept");
  openStep("Criteria");
  expect(stepRow("Criteria").textContent).not.toContain("Run the analysis to see the carving");
  expect(dimmedCarvingLayers()).toEqual([]);
});

test("threshold values given during a carving run: one more run follows with the last of them, and the carving stays dimmed until it ends", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  expect(service.count("GET /run/summary")).toBe(1);           // the carving the project opened with
  openStep("Criteria");
  expect(dimmedCarvingLayers()).toEqual([]);

  typeAndLeave(thresholdField(), "1");
  await settle();
  expect(service.runsStarted).toEqual([["thresholding"]]);     // run A, for 1
  for (const value of ["2", "3"]) typeAndLeave(thresholdField(), value);
  await settle();
  expect(service.runsStarted).toHaveLength(1);                 // 2 and 3 wait; 3 replaces 2

  let answerRunStart: () => void = () => {};
  service.runStartsWaitFor = new Promise((resolve) => { answerRunStart = resolve; });
  const runA = FakeWebSocket.opened[0];
  runA.send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  runA.send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  // A has ended and B, for 3, is saved and starting: nothing is fetched for 1, which the user left, and the carving stays dimmed.
  expect(service.savedValues.map(thresholdOf)).toEqual([1, 3]);
  expect(service.count("POST /runs")).toBe(2);
  expect(FakeWebSocket.opened).toHaveLength(1);
  expect(service.count("GET /run/summary")).toBe(1);
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels"]);

  answerRunStart();
  await settle();
  expect(FakeWebSocket.opened).toHaveLength(2);                // run B under way
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels"]);

  const runB = FakeWebSocket.opened[1];
  runB.send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  runB.send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(service.count("GET /run/summary")).toBe(2);
  expect(dimmedCarvingLayers()).toEqual([]);
  expect(service.runsStarted).toHaveLength(2);
});

test("a refused mode change locks the carving: the old mode's carving is not shown as current, and fixing the setting starts no analysis", async () => {
  service = new FakeService(CARVED, CARVING);
  // Daylight is refused for a carving setting until the user sets it, as a stored config.yaml or a run could leave it.
  service.configErrorsOf = (values) => (values.mode === "daylight" && values.max_slope_deg === undefined
    ? [{ field: "max_slope_deg", message: "Input should be greater than 0" }] : null);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  openPanelSection("Mode");
  act(() => modeTiles()[4].click());                                  // Daylight
  // Locked at once, before the save is sent: the stored settings, which the stage status describes, are still Solar time-based.
  expect(stepRow("Criteria").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
  await waitForTheSave();
  await settle();
  expect(service.count("PATCH /criteria/1")).toBe(1);
  expect(service.savedValues).toEqual([]);                     // refused: config.yaml still says Solar time-based
  expect(stepRow("Criteria").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
  expect(thresholdField().disabled).toBe(true);
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels", "sky_dome"]);
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("1 setting to fix");

  // The setting with the error stays editable in the locked carving rule; fixing it stores Daylight, and must not start a carving run,
  // which would run the whole analysis.
  const slope = container().querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="number"]')!;
  expect(slope.disabled).toBe(false);
  // Once Daylight is stored, the service finds the analysis out of date.
  service.stages = { ...CARVED, preprocessing: "out_of_date", thresholding: "out_of_date" };
  typeAndLeave(slope, "45");
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "daylight", max_slope_deg: 45 }]);
  expect(service.count("POST /runs")).toBe(0);
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(stepRow("Criteria").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
});

test("a failed run's link to a setting opens its step and focuses the input its label names: a slider's number field", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Site and grid");
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid", field_errors: [{ field: "voxel_size", message: "too small" }] });
  await settle();
  const link = [...container().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Go to voxel size")!;
  act(() => link.click());
  expect(document.activeElement).toBe(voxelSizeField());
});

test("the pinned bar folds the warnings of the last run behind one line", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "issue", stage: "preprocessing", code: "w", message: "1 panel skipped" });
  FakeWebSocket.opened[0].send({ type: "run_cancelled" });
  await settle();
  expect(pinnedBar().textContent).toContain("Cancelled.");
  const toggle = buttonIn(pinnedBar(), "1 warning");
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(pinnedBar().textContent).not.toContain("1 panel skipped");
  act(() => toggle.click());
  expect(pinnedBar().textContent).toContain("1 panel skipped");
});

test("go to a setting opens its section: a run refused for the analysis period, with Settings closed, focuses the period", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  expect(panelSectionOpen("Settings")).toBe(false);
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid",
                                 field_errors: [{ field: "start_month", message: "Input should be 12 or less" }] });
  await settle();
  expect(panelSectionOpen("Settings")).toBe(true);                  // the error marked in the field opened it
  togglePanelSection("Settings");
  expect(container().querySelector('[data-setting="start_month"]')).toBeNull();
  act(() => buttonIn(container(), "Go to analysis period").click());
  expect(panelSectionOpen("Settings")).toBe(true);
  expect(container().querySelector('[data-setting="start_month"]')!.contains(document.activeElement)).toBe(true);
});

test("go to a carving setting opens the Carving rule, closed before, and focuses the field", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  togglePanelSection("Carving rule");
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid",
                                 field_errors: [{ field: "max_slope_deg", message: "Input should be less than 90" }] });
  await settle();
  expect(panelSectionOpen("Carving rule")).toBe(true);              // the error marked in the field opened it
  togglePanelSection("Carving rule");
  act(() => buttonIn(container(), "Go to steepest step between columns").click());
  expect(panelSectionOpen("Carving rule")).toBe(true);
  expect(container().querySelector('[data-setting="max_slope_deg"]')!.contains(document.activeElement)).toBe(true);
});

test("go to the mode opens the Mode section and focuses the chosen tile", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid",
                                 field_errors: [{ field: "mode", message: "Input should be a valid mode" }] });
  await settle();
  expect(panelSectionOpen("Mode")).toBe(false);
  act(() => buttonIn(container(), "Go to mode").click());
  expect(panelSectionOpen("Mode")).toBe(true);
  expect(document.activeElement).toBe(container().querySelector('[role="radio"][aria-checked="true"]'));
});

test("closing the Carving rule while a threshold value waits for the carving run still starts the run that follows", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  typeAndLeave(thresholdField(), "1");
  await settle();
  expect(service.runsStarted).toEqual([["thresholding"]]);         // run A, for 1
  typeAndLeave(thresholdField(), "3");                              // waits for run A
  await settle();
  togglePanelSection("Carving rule");
  expect(container().querySelector(".threshold-control")).toBeNull();
  const runA = FakeWebSocket.opened[0];
  runA.send({ type: "stage_progress", stage: "thresholding", done: 0, total: 1 });
  runA.send({ type: "run_finished", stages: ["thresholding"], files: [] });
  await settle();
  expect(service.savedValues.map(thresholdOf)).toEqual([1, 3]);
  expect(service.count("POST /runs")).toBe(2);                      // run B, for 3
});

test("Build massing sends only massing and Build envelope only exporting; each leaves the other part's out-of-date mark (Review Focus 5)", async () => {
  // A threshold change and Run analysis since the last build: the envelope and the massing are both out of date.
  const stagesAfterAnalysis: Record<PipelineStage, StageState> = { ...CARVED, exporting: "out_of_date", massing: "out_of_date" };
  service = new FakeService(stagesAfterAnalysis, CARVING);
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: MASSING };
  await openWorkspace(service, project(stagesAfterAnalysis));
  openStep("Envelope and massing");
  const envelopeOutOfDate = () => buildPart("Envelope").querySelector(".envelope-results-out-of-date") !== null;
  const massingOutOfDate = () => buildPart("Building massing").querySelector(".envelope-results-out-of-date") !== null;
  expect([envelopeOutOfDate(), massingOutOfDate()]).toEqual([true, true]);
  expect(container().querySelector(".step-pinned-action")).toBeNull();          // each part has its own button

  await act(async () => buttonIn(buildPart("Building massing"), "Build massing").click());
  await settle();
  expect(service.runsStarted).toEqual([["massing"]]);
  // One run at a time: the envelope's button waits, saying why; the progress is under the button that started the run.
  expect(buttonIn(buildPart("Envelope"), "Build envelope").disabled).toBe(true);
  expect(reasonOf(buttonIn(buildPart("Envelope"), "Build envelope"))).toBe("A run is in progress");
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "massing", done: 0, total: 1 });
  await settle();
  expect(buildPart("Building massing").querySelector(".run-progress-stages")!.textContent).toContain("Building massing");
  expect(buildPart("Envelope").querySelector(".run-progress")).toBeNull();

  service.stages = { ...stagesAfterAnalysis, massing: "current" };
  run.send({ type: "run_finished", stages: ["massing"], files: [] });
  await settle();
  expect([envelopeOutOfDate(), massingOutOfDate()]).toEqual([true, false]);
  openStep("Criteria");
  expect(stepRow("Envelope and massing").querySelector(".step-summary")!.textContent).toBe("Envelope out of date, massing built");

  openStep("Envelope and massing");
  await act(async () => buttonIn(buildPart("Envelope"), "Build envelope").click());
  await settle();
  expect(service.runsStarted).toEqual([["massing"], ["exporting"]]);
  expect(FakeWebSocket.opened).toHaveLength(2);
  // Its volume arrives with the run summary once the envelope mesh is done.
  service.stages = { ...service.stages, exporting: "current" };
  service.summary = { ...service.summary, envelope: { mesh_file: "export.ply", envelope_volume_m3: 3900 } };
  FakeWebSocket.opened[1].send({ type: "run_finished", stages: ["exporting"], files: [] });
  await settle();
  expect(buildPart("Envelope").querySelector(".number-tile-value")!.textContent).toBe("3 900 m³");
  expect([envelopeOutOfDate(), massingOutOfDate()]).toEqual([false, false]);
});

test("while the carving is locked, Build envelope, Build massing and the Build envelope and massing of Criteria are disabled and say why (M10)", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);
  await openWorkspace(service, project(built));
  openStep("Envelope and massing");
  expect(buttonIn(buildPart("Envelope"), "Build envelope").disabled).toBe(false);

  // A voxel size typed and not saved yet: the analysis is out of date for the settings shown, and a build would run it.
  openStep("Site and grid");
  type(voxelSizeField(), "2");
  const lockReason = "Settings changed: run the analysis again before building";
  openStep("Envelope and massing");
  for (const [part, label] of [["Envelope", "Build envelope"], ["Building massing", "Build massing"]]) {
    const button = buttonIn(buildPart(part), label);
    expect(button.disabled).toBe(true);
    expect(reasonOf(button)).toBe(lockReason);
  }
  openStep("Criteria");
  const carvingBuild = buttonIn(pinnedBar(), "Build envelope and massing");
  expect(carvingBuild.disabled).toBe(true);
  expect(reasonOf(carvingBuild)).toBe(lockReason);

  // Stored, the service finds the analysis out of date: the lock holds until Run analysis.
  service.stages = { preprocessing: "out_of_date", thresholding: "out_of_date", exporting: "out_of_date", massing: "out_of_date" };
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ voxel_size: 2 }]);
  openStep("Envelope and massing");
  expect(buttonIn(buildPart("Building massing"), "Build massing").disabled).toBe(true);
  expect(service.count("POST /runs")).toBe(0);
});

test("while the carving is locked, a mesh format change is stored but builds nothing, and Export says why (M10)", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);
  await openWorkspace(service, project(built, { final_mesh_format: "ply" }));
  const lockReason = "Settings changed: run the analysis again before building";
  const formatField = () => container().querySelector('[data-setting="final_mesh_format"]')!;
  openStep("Export");
  expect(formatField().textContent).not.toContain(lockReason);

  openStep("Site and grid");
  service.stages = { preprocessing: "out_of_date", thresholding: "out_of_date", exporting: "out_of_date", massing: "out_of_date" };
  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  openStep("Export");
  expect(formatField().textContent).toContain(lockReason);
  await act(async () => formatField().querySelector<HTMLInputElement>('input[value="obj"]')!.click());
  await settle();
  expect(service.savedValues.at(-1)).toEqual({ final_mesh_format: "obj", voxel_size: 2 });
  expect(service.count("POST /runs")).toBe(0);                  // a run would start with the analysis
});

test("the Build envelope and massing of Criteria opens the step, builds both parts, shows its run at the top of the step and blocks both buttons", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Criteria");
  await act(async () => buttonIn(pinnedBar(), "Build envelope and massing").click());
  await settle();
  expect(stepRow("Envelope and massing").classList.contains("step-open")).toBe(true);
  expect(service.runsStarted).toEqual([["exporting", "massing"]]);
  const run = FakeWebSocket.opened[0];
  run.send({ type: "stage_progress", stage: "exporting", done: 0, total: 1 });
  await settle();
  const stepContent = container().querySelector(".envelope-step")!;
  const progress = stepContent.querySelector(":scope > .run-progress")!;
  expect(progress.textContent).toContain("Envelope mesh");
  expect(progress.compareDocumentPosition(buildPart("Envelope")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  for (const [part, label] of [["Envelope", "Build envelope"], ["Building massing", "Build massing"]]) {
    expect(reasonOf(buttonIn(buildPart(part), label))).toBe("A run is in progress");
    expect(buildPart(part).querySelector(".run-progress")).toBeNull();
  }

  // The envelope was written, then the massing failed: the run records neither, so the envelope's volume is not shown as built.
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: null };
  run.send({ type: "stage_progress", stage: "massing", done: 0, total: 1 });
  await settle();
  run.send({ type: "run_failed", error_type: "RuntimeError", message: "massing failed", field_errors: [] });
  await settle();
  expect(service.count("GET /run/summary")).toBeGreaterThan(1);
  expect(buildPart("Envelope").querySelector(".envelope-results")).toBeNull();
  openStep("Criteria");
  expect(stepRow("Envelope and massing").querySelector(".step-summary")!.textContent).toBe("Not built yet");
});

test("a workspace made again for a renamed project opens with the steps it had open, and says when they change", async () => {
  service = new FakeService(CARVED, CARVING);
  const stepsReported = vi.fn();
  await openWorkspace(service, project(CARVED), { startSteps: { open: "criteria", view: "criteria" }, onStepsChange: stepsReported });
  expect(stepRow("Criteria").classList.contains("step-open")).toBe(true);
  expect(stepRow("Inputs").classList.contains("step-open")).toBe(false);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(FakeViewerScene.latest!.visibleLayers.has("max_volume")).toBe(true);         // the layers of Criteria, the maximum volume as a ghost
  openStep("Export");
  expect(stepsReported).toHaveBeenLastCalledWith({ open: "export", view: "export", criteria: { shows: "editor", criterionId: "1" } });      // the one criterion's editor
  expect(FakeViewerScene.latest!.visibleLayers.has("max_volume")).toBe(false);
});

test("the Criteria step shows the kept voxels and starts with the carved ones hidden", () => {
  expect(LAYERS_SHOWN_IN_STEP.criteria).toContain("kept_voxels");
  expect(LAYERS_SHOWN_IN_STEP.criteria).not.toContain("carved_voxels");
});

test("the saver of the open project waits for an upload in flight, so a rename, reset or delete comes after it", async () => {
  service = new FakeService(CARVED, CARVING);
  let answerUpload: () => void = () => {};
  service.uploadsAnswerWhen = new Promise((resolve) => { answerUpload = resolve; });
  let saver: OpenProjectSettingsSaver | null = null;
  await openWorkspace(service, project(CARVED), { onSettingsSaverReady: (ready) => { saver = ready; } });
  const maximumVolumePicker = container().querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(maximumVolumePicker, "files", { value: [new File([TRIANGLE_OBJ], "more.obj")], configurable: true });
  act(() => maximumVolumePicker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  expect(service.requests).toContain("POST /inputs/max_volume");
  let uploadsEnded = false;
  void saver!.waitForInputChanges().then(() => { uploadsEnded = true; });
  await settle();
  expect(uploadsEnded).toBe(false);
  await act(async () => answerUpload());
  await settle();
  expect(uploadsEnded).toBe(true);
});

test("the saver of the open project waits for criterion requests in flight: a bypass, and the settings of a card just selected", async () => {
  let saver: OpenProjectSettingsSaver | null = null;
  let answerPatch: () => void = () => {};
  let answerSettings: () => void = () => {};
  await openChain([FACADES, WINDOWS, ROOFS], undefined, (chain) => {
    chain.patchesAnswerWhen = new Promise((resolve) => { answerPatch = resolve; });
    chain.settingsAnswerWhen["2"] = new Promise((resolve) => { answerSettings = resolve; });
  }, [], undefined, { onSettingsSaverReady: (ready) => { saver = ready; } });
  let ended = false;
  const waitForTheRequests = () => {
    ended = false;
    void saver!.waitForInputChanges().then(() => { ended = true; });
  };
  await act(async () => card("Daylight on roofs").querySelector<HTMLInputElement>('[role="switch"]')!.click());
  waitForTheRequests();
  await settle();
  expect(ended).toBe(false);                                     // PATCH criteria/3 has no reply yet
  await act(async () => answerPatch());
  await settle();
  expect(ended).toBe(true);
  await select("Spring sun on windows");
  waitForTheRequests();
  await settle();
  expect(ended).toBe(false);                                     // GET criteria/2/settings has no reply yet
  await act(async () => answerSettings());
  await settle();
  expect(ended).toBe(true);
});

// The notice of a new weather file (weather_change_notice.ts), over the criterion's settings in Criteria.
const BENEFIT_SCHEMA = {
  properties: { ...SCHEMA.properties, balance_temperature: { default: 15, type: "number" }, balance_offset: { default: 2, minimum: 0, type: "number" } },
};
const COLD_SEASON = { start_month: 9, start_day: 30, start_hour: 0, end_month: 5, end_day: 15, end_hour: 23 };
const MODES_WITH_BENEFIT: ModeInfo[] = [...MODES, { name: "benefit", description: "", needs_epw: true, needs_period: true, experimental: false,
                                                     score_kind: "weighted_sum", weight_unit: "", score_unit: "", starting_values: COLD_SEASON }];
const BRISBANE = { location: "Brisbane, AUS", latitude: -27.38 };
const GOLDEN = { location: "Golden, CO, USA", latitude: 39.74 };

async function addWeatherFile() {
  if (!stepRow("Inputs").classList.contains("step-open")) openStep("Inputs");
  const weatherPicker = container().querySelector<HTMLInputElement>('input[type="file"][accept=".epw"]')!;
  Object.defineProperty(weatherPicker, "files", { value: [new File(["LOCATION"], "weather.epw")], configurable: true });
  act(() => weatherPicker.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
  openStep("Criteria");
  openPanelSection("Settings");
}

/** Past the wait before the cold period is asked for, and its reply. */
const waitForTheColdPeriod = async () => {
  await act(async () => { await vi.advanceTimersByTimeAsync(450); });
  await settle();
};

const weatherNotice = () => container().querySelector<HTMLElement>(".weather-change-notice");
const noticeText = () => weatherNotice()!.querySelector("p")!.textContent;
const noticeRegion = () => container().querySelector<HTMLElement>(".weather-change-region");
const startDateHandle = () => container().querySelector<HTMLElement>('.period-control [role="slider"][aria-label="Start date"]');
const BRISBANE_SHIFT = "The new weather file (Brisbane, AUS) is in the southern hemisphere: winter there is June to August. " +
  "Shift the analysis period by six months, to 21 Jun, 10 to 14 h?";

test("a project opened with a weather file in the other hemisphere shows no notice: only a weather file added in this session does", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, { ...project(NOTHING_RUN), weather_location: BRISBANE.location, weather_latitude: BRISBANE.latitude });
  openStep("Criteria");
  expect(weatherNotice()).toBeNull();
});

test("a weather file in the other hemisphere: the notice offers the period six months on, which goes through the saver", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  expect(noticeText()).toBe(BRISBANE_SHIFT);
  expect(buttonIn(weatherNotice()!, "Keep").getAttribute("aria-label")).toBe("Keep the analysis period");
  act(() => buttonIn(weatherNotice()!, "Shift by six months").click());
  expect(weatherNotice()).toBeNull();
  expect(document.activeElement).toBe(startDateHandle());           // the focus goes to the period the button changed
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "time-based", start_month: 6, end_month: 6 }]);      // the settings changed, as the period control sends
});

test("a first weather file counts as after a northern one; the heating season preset follows the hemisphere of the file", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, { ...project(NOTHING_RUN), inputs: { ...project(NOTHING_RUN).inputs, weather: [] }, weather_location: null, weather_latitude: null });
  openStep("Criteria");
  openPanelSection("Settings");
  expect(buttonIn(container(), "Heating season, October to April")).toBeDefined();
  await addWeatherFile();
  expect(noticeText()).toContain("(Brisbane, AUS) is in the southern hemisphere");
  expect(buttonIn(container(), "Heating season, October to April")).toBeUndefined();
  expect(buttonIn(container(), "Heating season, April to October")).toBeDefined();
});

test("Keep dismisses the notice and saves nothing; a later weather file brings a notice again", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  act(() => buttonIn(weatherNotice()!, "Keep").click());
  expect(weatherNotice()).toBeNull();
  expect(document.activeElement).toBe(startDateHandle());
  await waitForTheSave();
  expect(service.savedValues).toEqual([]);
  service.uploadedWeather = GOLDEN;                 // back north, the period still northern: the notice asks about the change again
  await addWeatherFile();
  expect(noticeText()).toBe("The new weather file (Golden, CO, USA) is in the northern hemisphere: winter there is December to February. " +
    "Shift the analysis period by six months, to 21 Jun, 10 to 14 h?");
});

test("a weather file in the same hemisphere, or in a mode that reads no period, brings no notice", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();                           // Golden after Golden
  expect(weatherNotice()).toBeNull();
  unmountWorkspace();
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN, { mode: "daylight" }));
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();
});

test("while a run is in progress the notice's buttons are disabled, as the settings are", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  await pressRunAnalysis();
  for (const name of ["Shift by six months", "Keep"]) expect(buttonIn(weatherNotice()!, name).disabled).toBe(true);
});

test("Solar usefulness: the notice waits for the cold period of the new file and offers it, keeping the hours", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN, { mode: "benefit" }), {}, { schema: BENEFIT_SCHEMA, modes: MODES_WITH_BENEFIT });
  await waitForTheColdPeriod();                     // of the file the project opened with: none
  service.coldPeriodReply = { status: "found", period: { start_month: 5, start_day: 3, end_month: 9, end_day: 20 } };
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();               // waiting for the new file's answer
  await waitForTheColdPeriod();
  expect(noticeText()).toBe("The new weather file (Brisbane, AUS) has its cold period from 3 May to 20 Sep; the analysis period is 30 Sep to 15 May.");
  act(() => buttonIn(weatherNotice()!, "Use the cold period").click());
  expect(weatherNotice()).toBeNull();
  await waitForTheSave();
  await settle();
  expect(service.savedValues).toEqual([{ mode: "benefit", start_month: 5, start_day: 3, end_month: 9, end_day: 20 }]);           // the hours kept
});

test("Solar usefulness, energy-weighted: a new file's cold period is not offered, as it belongs to the cold hours rule", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  const energyWeighted = project(NOTHING_RUN, { mode: "benefit" });
  energyWeighted.criteria = energyWeighted.criteria!.map((criterion) => ({ ...criterion, energy_weighted: true }));
  await openWorkspace(service, energyWeighted, {}, { schema: BENEFIT_SCHEMA, modes: MODES_WITH_BENEFIT });
  await waitForTheColdPeriod();
  service.coldPeriodReply = { status: "found", period: { start_month: 5, start_day: 3, end_month: 9, end_day: 20 } };
  await addWeatherFile();
  await waitForTheColdPeriod();
  expect(weatherNotice()).toBeNull();
});

test("Solar usefulness: no cold period in the new file, or the one the period already has, brings no notice", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN, { mode: "benefit" }), {}, { schema: BENEFIT_SCHEMA, modes: MODES_WITH_BENEFIT });
  await addWeatherFile();                           // the service finds no cold period
  await waitForTheColdPeriod();
  expect(weatherNotice()).toBeNull();
  service.coldPeriodReply = { status: "found", period: { start_month: 9, start_day: 30, end_month: 5, end_day: 15 } };
  await addWeatherFile();
  await waitForTheColdPeriod();
  expect(weatherNotice()).toBeNull();
});

test("the notice is a live region kept on the page, empty until a notice fills it, so screen readers announce what comes", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  expect(noticeRegion()!.getAttribute("role")).toBe("status");
  expect(noticeRegion()!.textContent).toBe("");
  await addWeatherFile();                                           // through the Inputs step, back to Criteria
  const region = noticeRegion()!;
  expect(region.textContent).toContain(BRISBANE_SHIFT);
  act(() => buttonIn(weatherNotice()!, "Keep").click());
  expect(noticeRegion()).toBe(region);
  expect(region.textContent).toBe("");
});

test("a new weather file without a latitude keeps the hemisphere of the one before it", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  act(() => buttonIn(weatherNotice()!, "Keep").click());          // the period stays northern, the file southern
  service.uploadedWeather = { location: null, latitude: null } as unknown as typeof BRISBANE;
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();                               // nothing to say about a file without a latitude
  service.uploadedWeather = GOLDEN;
  await addWeatherFile();                                           // north after the southern file: the notice asks
  expect(noticeText()).toContain("(Golden, CO, USA) is in the northern hemisphere");
});

test("a weather file in the tropics brings no notice and keeps the northern heating season preset", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = { location: "Darwin, AUS", latitude: -12.46 };
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  expect(weatherNotice()).toBeNull();
  expect(buttonIn(container(), "Heating season, October to April")).toBeDefined();
});

test("once the period is changed by hand the notice is gone, also when the period is set back", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.uploadedWeather = BRISBANE;
  await openWorkspace(service, project(NOTHING_RUN));
  await addWeatherFile();
  expect(noticeText()).toBe(BRISBANE_SHIFT);
  act(() => buttonIn(container(), "21 June").click());
  expect(weatherNotice()).toBeNull();
  act(() => buttonIn(container(), "21 December").click());          // the period the file came with, again
  await waitForTheSave();
  await settle();
  expect(weatherNotice()).toBeNull();
});

// ---- Several criteria (spec 7.3): progress per criterion and on the cards, refusals at their card, the carving lock per
// criterion and the live rethreshold from an earlier criterion ----

const THRESHOLD_OUT_OF_DATE: CriterionStages = { preprocessing: "current", thresholding: "out_of_date" };
const NOT_RUN: CriterionStages = { preprocessing: "missing", thresholding: "missing" };
/** The stages of the run shown in the criterion's panel: each one's name and state. */
const stageRows = () => [...pinnedBar().querySelectorAll(".run-stage")]
  .map((row) => `${row.querySelector(".run-stage-name")!.textContent} | ${row.querySelector(".run-stage-state")!.textContent}`);
/** A card's result line of a mode that is not weighted, as formatNumber writes it (no-break spaces before the units). */
const volumeLine = (percent: number, volume: number) => `Removes ${volume} m³, ${percent} % of what reached it`;
/** How often *text* is on the page in *root*. */
const timesShown = (root: Element, text: string) => (root.textContent ?? "").split(text).length - 1;

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
  expect(cardLine("Winter sun on facades")).toBe(volumeLine(30, 300));
  expect(cardLine("Spring sun on windows")).toBe("Running");

  chainService.criterionStages = { 1: CURRENT, 2: CURRENT };
  chainService.summaryCriteria = [carvingSummaryOf(FACADES, 70), carvingSummaryOf(WINDOWS, 75)];
  run.send({ type: "run_finished", stages: ["preprocessing", "thresholding"], files: [] });
  await settle();
  expect(cardLine("Spring sun on windows")).toBe(volumeLine(25, 250));
});

test("the pinned bar scrolls when the run progress is long, and the step stays on the page", async () => {
  const removeStyleSheet = addStyleSheetForTest("src/steps/steps.css");
  try {
    await openChain([FACADES, WINDOWS], { 1: OUT_OF_DATE, 2: THRESHOLD_OUT_OF_DATE });
    chainService.runCriterionStages = { 1: ["preprocessing", "thresholding"], 2: ["preprocessing", "thresholding"] };
    await pressRunAnalysis();
    expect(stageRows()).toHaveLength(4);
    const bar = pinnedBar();
    expect(bar.classList.contains("step-pinned-action")).toBe(true);
    expect(bar.querySelectorAll(".run-stage")).toHaveLength(4);
    const style = getComputedStyle(bar);                          // jsdom has no layout: the class says it scrolls inside half the panel
    expect(style.maxHeight).toBe("50%");
    expect(style.overflowY).toBe("auto");
    expect(panel()).not.toBeNull();                               // the step above is still there to reach
    expect(card("Winter sun on facades")).toBeDefined();
  } finally {
    removeStyleSheet();
  }
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
  await openChain([FACADES, WINDOWS]);
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

test("the pinned run says what a criterion without test surfaces needs", async () => {
  await openChain([FACADES, WINDOWS]);
  // The service found criterion 2's test surfaces gone (removed in another tab, say).
  const refusal = "Add test surfaces to Spring sun on windows.";
  chainService.runRefusal = { status: 422, body: { detail: refusal, missing_inputs: ["test_surfaces:2"] } };
  await pressRunAnalysis();
  expect(timesShown(pinnedBar(), refusal)).toBe(1);
  expect(pinnedBar().querySelector(".run-outcome-error")!.textContent).toBe(refusal);
  expect(timesShown(panelFrame(), refusal)).toBe(0);              // the panel does not say it a second time
  // Known beforehand, the button waits and names the criterion.
  await openChain([FACADES, { ...WINDOWS, test_surface_files: [] }], { 1: CURRENT, 2: NOT_RUN });
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Add test surfaces to Spring sun on windows to run the analysis");
});

test("a run refused for missing test surfaces selects that criterion and asks for them once, in the pinned bar", async () => {
  await openChain([FACADES, WINDOWS]);
  // The service found criterion 2's test surfaces gone (removed in another tab, say).
  const refusal = "Add test surfaces to Spring sun on windows.";
  chainService.runRefusal = { status: 422, body: { detail: refusal, missing_inputs: ["test_surfaces:2"] } };
  await pressRunAnalysis();                                       // the pinned Run analysis, which says the refusal itself
  expect(selectedCardName()).toBe("Spring sun on windows");
  expect(timesShown(pinnedBar(), refusal)).toBe(1);
  expect(timesShown(panelFrame(), refusal)).toBe(0);
  // From Site and grid the refusal is said there; the panel of the criterion says it once too.
  await select("Winter sun on facades");
  openStep("Site and grid");
  await pressRunAnalysis();
  openStep("Criteria");
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
  expect(reasonOf(runButton())).toBe("Add test surfaces to Spring sun on windows to run the analysis");
  // A carving change of criterion 1 waits for criterion 2, which needs test surfaces before any analysis.
  expect(panel().textContent).toContain("Add test surfaces to Spring sun on windows first");
  expect(panel().textContent).not.toContain("Run the analysis for Spring sun on windows first");
  // Shown, it is named too: with several criteria the bar says which one the reason is about.
  await select("Spring sun on windows");
  expect(reasonOf(runButton())).toBe("Add test surfaces to Spring sun on windows to run the analysis");
  await bypass("Spring sun on windows");
  expect(runButton().disabled).toBe(false);
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
  expect(cardLine("Spring sun on windows")).toBe(volumeLine(25, 250));
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
  expect(panel().textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
});

test("a run refused for criterion 2's settings, seen from criterion 1, names criterion 2; its link selects it and focuses the field", async () => {
  await openChain([FACADES, WINDOWS]);
  chainService.runRefusal = {
    status: 422, body: { field_errors: [{ field: "max_slope_deg", message: "Input should be less than 90" }], grid_plan: null, criterion: "2" },
  };
  await pressRunAnalysis();
  expect(pinnedBar().textContent).toContain("The run stopped on an error.");          // said in the pinned bar; criterion 2 is selected
  await select("Winter sun on facades");
  expect(pinnedBar().textContent).toContain("The run stopped on an error in the settings of Spring sun on windows.");
  const link = buttonIn(pinnedBar(), "Go to steepest step between columns of Spring sun on windows");
  await act(async () => link.click());
  await settle();
  expect(container().querySelector('[data-setting="max_slope_deg"]')!.contains(document.activeElement)).toBe(true);
  expect(selectedCardName()).toBe("Spring sun on windows");
});

test("go to a setting of another criterion, its section closed: that criterion is selected, the section opens and the field has the focus", async () => {
  await openChain([FACADES, WINDOWS]);
  chainService.runRefusal = {
    status: 422, body: { field_errors: [{ field: "start_month", message: "Input should be 12 or less" }], grid_plan: null, criterion: "2" },
  };
  await pressRunAnalysis();                                       // selects criterion 2, whose marked field opens Settings
  await select("Winter sun on facades");
  expect(panelSectionOpen("Settings")).toBe(true);
  togglePanelSection("Settings");
  await act(async () => buttonIn(pinnedBar(), "Go to analysis period of Spring sun on windows").click());
  await settle();
  expect(panelSectionOpen("Settings")).toBe(true);
  expect(container().querySelector('[data-setting="start_month"]')!.contains(document.activeElement)).toBe(true);
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

test("Site and grid's Run analysis names the criterion without test surfaces, whichever criterion is shown", async () => {
  await openChain([FACADES, { ...WINDOWS, test_surface_files: [] }], { 1: CURRENT, 2: NOT_RUN });
  await select("Spring sun on windows");
  openStep("Site and grid");
  const runButton = buttonIn(pinnedBar(), "Run analysis");
  expect(reasonOf(runButton)).toBe("Add test surfaces to Spring sun on windows to run the analysis");
});

test("Run analysis asks for the weather file a criterion that is on needs, naming it, also when the shown one needs none", async () => {
  const withoutWeatherFile = (opened: ProjectDetail): ProjectDetail => ({ ...opened, inputs: { ...opened.inputs, weather: [] } });
  await openChain([{ ...ROOFS, id: "1" }, { ...FACADES, id: "2" }], undefined, undefined, [], withoutWeatherFile);
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Add a weather file to run Winter sun on facades");
  openStep("Site and grid");
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Add a weather file to run Winter sun on facades");
  openStep("Criteria");
  await select("Winter sun on facades");
  expect(reasonOf(buttonIn(pinnedBar(), "Run analysis"))).toBe("Add a weather file to run Winter sun on facades");
});

test("a criterion that is off is not flagged for a missing weather file", async () => {
  const withoutWeatherFile = (opened: ProjectDetail): ProjectDetail => ({ ...opened, inputs: { ...opened.inputs, weather: [] } });
  await openChain([{ ...ROOFS, id: "1" }, { ...FACADES, id: "2", bypassed: true }], undefined, undefined, [], withoutWeatherFile);
  await select("Winter sun on facades");
  expect(panelSectionOpen("Mode")).toBe(false);
  expect(panel().querySelector('.panel-section[data-section="mode"] .panel-section-summary')!.textContent).toBe("Solar time-based");
  expect(panel().querySelector(".panel-section-summary-problem")).toBeNull();
  expect(pinnedBar().textContent).not.toContain("weather file");
});

test("a shared setting refused by another criterion's settings is said in Site and grid with that criterion's name, on no criterion field", async () => {
  await openChain([FACADES, WINDOWS], undefined, (chain) => {
    chain.configErrorsOf = (values) => (values.voxel_size === 3 ? [{ field: "max_slope_deg", message: "Input should be less than 90" }] : null);
    chain.sharedRefusalCriterion = "2";
  });
  openStep("Site and grid");
  typeAndLeave(voxelSizeField(), "3");
  await waitForTheSave();
  await settle();
  expect(stepRow("Site and grid").textContent).toContain("Spring sun on windows: Steepest step between columns: Input should be less than 90");
  openStep("Criteria");
  expect(container().querySelector('[data-setting="max_slope_deg"] .setting-error')).toBeNull();     // criterion 1's own field is fine
});
