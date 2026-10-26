// The open project as a whole, against a fake service: settings saves, the run loop, the stage status and the locks and
// build buttons that follow from them, as the unit tests of each cannot show them together.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import type { ModeInfo } from "../api_client/client";
import { LAYERS_SHOWN_IN_STEP, type OpenProjectSettingsSaver } from "./ProjectWorkspace";
import type { PipelineStage, StageState } from "./step_summaries";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, MODES, NOTHING_RUN, SCHEMA, TRIANGLE_OBJ, buildPart, buttonIn, container,
  dimmedCarvingLayers, endWorkspaceTest, openStep, openWorkspace, pressRunAnalysis, project, reasonOf, settle,
  startWorkspaceTest, stepRow, thresholdField, thresholdOf, type, typeAndLeave, unmountWorkspace, voxelSizeField,
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
  openStep("Settings");

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
  expect(stepRow("Carving").classList.contains("step-open")).toBe(true);    // a finished analysis opens Carving
  expect(stepRow("Carving").textContent).toContain("Volume kept61 %");
  expect(dimmedCarvingLayers()).toEqual([]);
  openStep("Settings");
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("61\u00a0% kept");
});

test("a save the service refuses keeps Run analysis from starting a run, and says why", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.refuseSavesWith = 409;
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Settings");

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
const settingsSummaryText = () => stepRow("Settings").querySelector(".step-summary")!.textContent;

test("saving the voxel size sends only shared settings", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { start_month: 3, north_deg: 10 }));
  openStep("Settings");
  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PUT /shared-settings"]);
  expect(service.savedValues).toEqual([{ north_deg: 10, voxel_size: 2 }]);     // no mode, no setting of the criterion
});

test("saving the analysis period sends the criterion's settings", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { voxel_size: 2, threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Settings");
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
  openStep("Carving");
  act(() => stepRow("Carving").querySelector<HTMLButtonElement>(".setting-fold")!.click());      // More carving settings
  typeAndLeave(container().querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="number"]')!, "100");
  await waitForTheSave();
  await settle();
  expect(new Set(settingsSaves())).toEqual(new Set(["PATCH /criteria/1"]));
  expect(service.savedValues).toEqual([]);
  expect(container().querySelector('[data-setting="max_slope_deg"] .setting-error')!.textContent).toBe("Input should be less than 90");
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("1 setting to fix");
  expect(service.count("POST /runs")).toBe(0);
});

test("a mode change starts the criterion from the new mode's values", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { voxel_size: 2, start_month: 3 }));
  expect(settingsSummaryText()).toContain("21 Mar");
  openStep("Mode");
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
  expect(settingsSummaryText()).toContain("21 Dec");
  expect(settingsSummaryText()).toContain("2 m");                // the shared voxel size stays
});

test("a page opened during a run it does not follow: Run analysis answered with up to date brings the carving the service holds", async () => {
  service = new FakeService(CARVED, CARVING);                  // the run has ended since
  service.everythingUpToDate = true;
  await openWorkspace(service, project(NOTHING_RUN));                   // opened while the run had removed the stage records
  openStep("Settings");
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("Not run yet");

  await pressRunAnalysis();
  expect(container().querySelector(".step-pinned-action")!.textContent).toContain("Results are up to date");
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(service.count("GET /run/summary")).toBe(1);
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("61\u00a0% kept");
  openStep("Carving");
  expect(stepRow("Carving").textContent).not.toContain("Run the analysis in Settings to see the carving");
  expect(dimmedCarvingLayers()).toEqual([]);
});

test("threshold values given during a carving run: one more run follows with the last of them, and the carving stays dimmed until it ends", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  expect(service.count("GET /run/summary")).toBe(1);           // the carving the project opened with
  openStep("Carving");
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

test("a refused mode change locks Carving: the old mode's carving is not shown as current, and fixing the setting starts no analysis", async () => {
  service = new FakeService(CARVED, CARVING);
  // Daylight is refused for a carving setting until the user sets it, as a stored config.yaml or a run could leave it.
  service.configErrorsOf = (values) => (values.mode === "daylight" && values.max_slope_deg === undefined
    ? [{ field: "max_slope_deg", message: "Input should be greater than 0" }] : null);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Mode");
  act(() => [...container().querySelectorAll<HTMLElement>('[role="radio"]')][4].click());      // Daylight
  // Locked at once, before the save is sent: the stored settings, which the stage status describes, are still Solar time-based.
  openStep("Carving");
  expect(stepRow("Carving").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
  await waitForTheSave();
  await settle();
  expect(service.count("PATCH /criteria/1")).toBe(1);
  expect(service.savedValues).toEqual([]);                     // refused: config.yaml still says Solar time-based
  expect(stepRow("Carving").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
  expect(thresholdField().disabled).toBe(true);
  expect(dimmedCarvingLayers()).toEqual(["carved_voxels", "kept_voxels", "sky_dome"]);
  expect(stepRow("Carving").querySelector(".step-summary")!.textContent).toBe("1 setting to fix");

  // The setting with the error stays editable in the locked step; fixing it stores Daylight, and must not start a carving run,
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
  expect(stepRow("Carving").textContent).toContain("Settings changed since the analysis. Run the analysis again to update the carving.");
});

test("a failed run's link to a setting opens its step and focuses the input its label names: a slider's number field", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Settings");
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid", field_errors: [{ field: "voxel_size", message: "too small" }] });
  await settle();
  const link = [...container().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Go to voxel size")!;
  act(() => link.click());
  expect(document.activeElement).toBe(voxelSizeField());
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
  openStep("Carving");
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

test("while Carving is locked, Build envelope, Build massing and Carving's Build envelope and massing are disabled and say why (M10)", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);
  await openWorkspace(service, project(built));
  openStep("Envelope and massing");
  expect(buttonIn(buildPart("Envelope"), "Build envelope").disabled).toBe(false);

  // A voxel size typed and not saved yet: the analysis is out of date for the settings shown, and a build would run it.
  openStep("Settings");
  type(voxelSizeField(), "2");
  const lockReason = "Settings changed since the analysis. Run the analysis again before building.";
  openStep("Envelope and massing");
  for (const [part, label] of [["Envelope", "Build envelope"], ["Building massing", "Build massing"]]) {
    const button = buttonIn(buildPart(part), label);
    expect(button.disabled).toBe(true);
    expect(reasonOf(button)).toBe(lockReason);
  }
  openStep("Carving");
  const carvingBuild = buttonIn(container().querySelector(".step-pinned-action")!, "Build envelope and massing");
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

test("while Carving is locked, a mesh format change is stored but builds nothing, and Export says why (M10)", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);
  await openWorkspace(service, project(built, { final_mesh_format: "ply" }));
  const lockReason = "Settings changed since the analysis. Run the analysis again before building.";
  const formatField = () => container().querySelector('[data-setting="final_mesh_format"]')!;
  openStep("Export");
  expect(formatField().textContent).not.toContain(lockReason);

  openStep("Settings");
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

test("Carving's Build envelope and massing opens the step, builds both parts, shows its run at the top of the step and blocks both buttons", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  openStep("Carving");
  await act(async () => buttonIn(container().querySelector(".step-pinned-action")!, "Build envelope and massing").click());
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
  openStep("Carving");
  expect(stepRow("Envelope and massing").querySelector(".step-summary")!.textContent).toBe("Not built yet");
});

test("a workspace made again for a renamed project opens with the steps it had open, and says when they change", async () => {
  service = new FakeService(CARVED, CARVING);
  const stepsReported = vi.fn();
  await openWorkspace(service, project(CARVED), { startSteps: { open: "carving", view: "carving" }, onStepsChange: stepsReported });
  expect(stepRow("Carving").classList.contains("step-open")).toBe(true);
  expect(stepRow("Inputs").classList.contains("step-open")).toBe(false);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(FakeViewerScene.latest!.visibleLayers.has("max_volume")).toBe(false);        // the view shows the carving's layers, not the inputs' ones
  openStep("Export");
  expect(stepsReported).toHaveBeenLastCalledWith({ open: "export", view: "export" });
});

test("the Carving step shows the kept voxels and starts with the carved ones hidden", () => {
  expect(LAYERS_SHOWN_IN_STEP.carving).toContain("kept_voxels");
  expect(LAYERS_SHOWN_IN_STEP.carving).not.toContain("carved_voxels");
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

// The notice of a new weather file (weather_change_notice.ts) in the Settings step.
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
  openStep("Settings");
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
  openStep("Settings");
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
  openStep("Settings");
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
  openStep("Settings");
  expect(noticeRegion()!.getAttribute("role")).toBe("status");
  expect(noticeRegion()!.textContent).toBe("");
  await addWeatherFile();                                           // through the Inputs step, back to Settings
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
