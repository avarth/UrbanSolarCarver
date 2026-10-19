// The open project as a whole, against a fake service: settings saves, the run loop, the stage status and the locks and
// build buttons that follow from them, as the unit tests of each cannot show them together.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import type { OpenProjectSettingsSaver } from "./ProjectWorkspace";
import type { PipelineStage, StageState } from "./step_summaries";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, NOTHING_RUN, TRIANGLE_OBJ, buildPart, buttonIn, container,
  dimmedCarvingLayers, endWorkspaceTest, openStep, openWorkspace, pressRunAnalysis, project, reasonOf, settle,
  startWorkspaceTest, stepRow, thresholdField, thresholdOf, type, typeAndLeave, voxelSizeField, waitForTheSave,
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
  expect(service.savedValues).toEqual([{ mode: "time-based", voxel_size: 2 }]);
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
  expect(service.count("PUT /config")).toBe(2);                // Run analysis sent the change again first
  expect(service.runsStarted).toEqual([]);
  expect(FakeWebSocket.opened).toHaveLength(0);
  expect(notice()).not.toBeNull();
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
  expect(service.count("PUT /config")).toBe(1);
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
  expect(service.savedValues).toEqual([{ mode: "time-based", voxel_size: 2 }]);
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
  expect(service.savedValues.at(-1)).toEqual({ mode: "time-based", final_mesh_format: "obj", voxel_size: 2 });
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
