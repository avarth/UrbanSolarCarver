// The open project of one criterion as a whole, against a fake service: settings saves, the run loop, the stage status and the
// locks and build buttons that follow from them, as the unit tests of each cannot show them together. The notice of a new weather
// file is in ProjectWorkspace.weather_notice, the runs and saves of several criteria in ProjectWorkspace.chain_runs.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { FakeWebSocket } from "../api_client/fake_websocket_for_test";
import { FakeViewerScene } from "../viewer/fake_scene_for_test";
import { packScorePoints } from "../viewer/packed_results_for_test";
import { byRole } from "../viewer_overlays/render_for_test";
import type { OpenProjectSettingsSaver } from "./ProjectWorkspace";
import type { PipelineStage, StageState } from "../stages";
import { FACADES, ROOFS, WINDOWS, card, openChain, select } from "./chain_service_for_test";
import {
  CARVED, CARVING, ENVELOPE, FakeService, MASSING, NOTHING_RUN, TRIANGLE_OBJ, addWeatherFileInSettings, buildPart, buttonIn, container,
  dimmedCarvingLayers, endWorkspaceTest, openPanelSection, openStep, closeProjectSettings, openProjectSettings, projectSettings, settingsButton, settingsWeatherBox, openWorkspace, panelSectionOpen, pinnedBar, pressRunAnalysis, project, reasonOf, reportedServiceProblems, settle,
  startWorkspaceTest, stepIsOpen, stepRow, thresholdField, thresholdOf, togglePanelSection, type, typeAndLeave, voxelSizeField, waitForTheSave,
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
  openProjectSettings();

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
  expect(stepIsOpen("Criteria")).toBe(true);                                 // a finished analysis opens Criteria
  expect(stepRow("Criteria").textContent).toContain("Shade allowed per voxel");     // the carving rule, no longer waiting
  expect(stepRow("Criteria").textContent).not.toContain("Run the analysis to see the carving");
  expect(dimmedCarvingLayers()).toEqual([]);
  openStep("Site");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Sun hours, 61\u00a0% kept");
});

test("a save the service refuses keeps Run analysis from starting a run, and says why", async () => {
  service = new FakeService(NOTHING_RUN, null);
  service.refuseSavesWith = 409;
  await openWorkspace(service, project(NOTHING_RUN));
  openProjectSettings();

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
/** The tile of the mode named *name*, by its accessible name (not its place in mode_tiles.json). */
const modeTile = (name: string) => byRole(container(), "radio", name);
const settingsSummaryText = () => settingsButton().title;

test("saving the voxel size sends only shared settings", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN, { start_month: 3, north_deg: 10 }));
  openProjectSettings();
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
  // The form keeps a value outside the schema's bounds (at most 90) from being sent, so the fake refuses one inside them.
  service.configErrorsOf = (values) => (values.max_slope_deg === 60 ? [{ field: "max_slope_deg", message: "The fake service refuses 60." }] : null);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  openStep("Criteria");
  act(() => stepRow("Criteria").querySelector<HTMLButtonElement>(".carving-settings .setting-fold")!.click());      // More carving settings
  typeAndLeave(container().querySelector<HTMLInputElement>('[data-setting="max_slope_deg"] input[type="number"]')!, "60");
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect(service.savedValues).toEqual([]);
  expect(container().querySelector('[data-setting="max_slope_deg"] .setting-error')!.textContent).toBe("The fake service refuses 60.");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("1 setting to fix");
  expect(service.count("POST /runs")).toBe(0);
});

test("a new project shows the mode tiles in place of its criterion; a tile sets the mode, says so to the service and opens the editor", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, { ...project(NOTHING_RUN, { voxel_size: 2 }), mode_to_choose: true });
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Choose a mode");
  openStep("Criteria");
  expect(container().querySelector(".first-mode-title")!.textContent).toBe("Choose a mode for the first criterion");
  expect(container().querySelector(".criterion-panel")).toBeNull();
  act(() => modeTile("Daylight").click());
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PATCH /criteria/1"]);
  expect(service.savedValues).toEqual([{ mode: "daylight" }]);         // not the shared voxel size
  expect(service.count("POST /mode-chosen")).toBe(1);
  expect(container().querySelector(".first-mode")).toBeNull();
  expect(container().querySelector(".criterion-panel")).not.toBeNull();
  expect(settingsSummaryText()).toContain("2\u00a0m");
});

test("a project whose mode is chosen goes straight to its criterion", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  openStep("Criteria");
  expect(container().querySelector(".first-mode")).toBeNull();
  expect(container().querySelector(".criterion-panel")).not.toBeNull();
});

test("a shared change refused for the criterion's mode is saved again once the first mode makes it storable, and Run analysis starts", async () => {
  service = new FakeService(NOTHING_RUN, null);
  // The service checks the shared settings with the criterion: Sun hours needs the weather file the project lacks.
  service.configErrorsOf = (values) => ("voxel_size" in values && service.criterionSettings.mode === "time-based"
    ? [{ field: null, message: "Value error, mode 'time-based' requires epw_path" }] : null);
  await openWorkspace(service, { ...project(NOTHING_RUN), inputs: { ...project(NOTHING_RUN).inputs, weather: [] }, weather_location: null, weather_latitude: null, mode_to_choose: true });
  openProjectSettings();
  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  expect(settingsSaves()).toEqual(["PUT /shared-settings"]);
  expect(projectSettings()!.querySelector(".step-error")!.textContent).toBe("Add a weather file in Settings to run this mode");

  closeProjectSettings();
  openStep("Criteria");
  act(() => modeTile("Daylight").click());                            // Daylight reads no weather file
  await waitForTheSave();
  await settle();
  await waitForTheSave();                                             // the shared settings, sent again after the criterion's save
  await settle();
  expect(settingsSaves()).toEqual(["PUT /shared-settings", "PATCH /criteria/1", "PUT /shared-settings"]);
  expect(service.savedValues).toEqual([{ mode: "daylight" }, { voxel_size: 2 }]);
  openProjectSettings();
  expect(projectSettings()!.querySelector(".step-error")).toBeNull();
  await pressRunAnalysis();
  expect(service.runsStarted).toEqual([["thresholding"]]);
});

describe("the sky dome of a finished run", () => {
  const openWithSkyPatches = async (failWith: number | null) => {
    service = new FakeService(CARVED, CARVING);
    service.summary = { carving: CARVING, envelope: null, massing: null };
    service.runSkyPatchesFailWith = failWith;
    await openWorkspace(service, project(CARVED));
  };
  const skyDomeEntry = async () => {
    await act(async () => buttonIn(container(), "Layers").click());
    return [...container().querySelectorAll("li")].find((item) => item.textContent?.startsWith("Sky dome"));
  };

  test("a run without sky patches lists no Sky dome: nothing is missing", async () => {
    await openWithSkyPatches(null);
    expect(await skyDomeEntry()).toBeUndefined();
    expect(reportedServiceProblems).toEqual([]);
  });

  test("sky patches that cannot be read list the Sky dome as missing, saying how to write them again", async () => {
    await openWithSkyPatches(500);
    const entry = (await skyDomeEntry())!;
    expect(entry.querySelector("input")!.disabled).toBe(true);
    expect(entry.textContent).toContain("could not be read");
  });

  test("access lost while they are read is reported to the app, not as a missing layer", async () => {
    await openWithSkyPatches(401);
    expect(reportedServiceProblems).toHaveLength(1);
    expect(await skyDomeEntry()).toBeUndefined();
  });
});

test("a page opened during a run it does not follow: Run analysis answered with up to date brings the carving the service holds", async () => {
  const built: Record<PipelineStage, StageState> = { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" };
  service = new FakeService(built, CARVING);                   // the run has ended since
  service.summary = { carving: CARVING, envelope: ENVELOPE, massing: MASSING };
  service.everythingUpToDate = true;
  // Opened while the run had removed the records of the stages it rewrote: the envelope and the massing were still current.
  await openWorkspace(service, project({ ...built, preprocessing: "missing", thresholding: "missing" }));
  openStep("Site");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Sun hours, Not run yet");

  const requestsBefore = service.requests.length;
  await pressRunAnalysis();
  expect(container().querySelector(".step-pinned-action")!.textContent).toContain("Results are up to date");
  expect(FakeWebSocket.opened).toHaveLength(0);
  // The carving and the analysis before it, which the page did not hold as current, are asked for; not the envelope or the massing.
  expect(service.requests.slice(requestsBefore).filter((request) => request.startsWith("GET /run/"))
    .map((request) => request.split("?")[0]).sort())
    .toEqual(["GET /run/score-points", "GET /run/skipped-surfaces", "GET /run/sky-patches", "GET /run/summary"]);
  openStep("Site");
  expect(stepRow("Criteria").querySelector(".step-summary")!.textContent).toBe("Sun hours, 61\u00a0% kept");
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

test("a failed run's link to a shared setting opens the project settings and focuses the input its label names: a slider's number field", async () => {
  service = new FakeService(NOTHING_RUN, null);
  await openWorkspace(service, project(NOTHING_RUN));
  await pressRunAnalysis();
  FakeWebSocket.opened[0].send({ type: "run_failed", error_type: "ConfigError", message: "invalid", field_errors: [{ field: "voxel_size", message: "too small" }] });
  await settle();
  expect(projectSettings()).toBeNull();
  const link = [...container().querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Go to voxel size")!;
  act(() => link.click());
  expect(projectSettings()).not.toBeNull();
  expect(document.activeElement).toBe(voxelSizeField());
  closeProjectSettings();
  expect(document.activeElement).toBe(settingsButton());          // the focus goes back to the button
});

test("a stored grid over the budget marks the Settings button, and Run analysis names Settings with a button that opens it at Voxel size", async () => {
  service = new FakeService(NOTHING_RUN, null);
  const overBudget = { resolution: 2000, voxel_size: 0.05, total_voxels: 8_000_000_000, extent: 100, budget_voxels: 500_000_000 };
  await openWorkspace(service, { ...project(NOTHING_RUN, { voxel_size: 0.05 }), grid_plan: overBudget });
  expect(settingsButton().getAttribute("aria-label")).toBe("Settings, 1 setting to fix");
  expect(settingsButton().querySelector(".step-mark-error")).not.toBeNull();
  for (const title of ["Site", "Criteria", "Envelope and massing", "Export"]) expect(stepRow(title).querySelector(".step-mark-error"), title).toBeNull();
  openStep("Criteria");
  const run = buttonIn(pinnedBar(), "Run analysis");
  expect(run.disabled).toBe(true);
  expect(reasonOf(run)).toBe("Fix the voxel size in Settings to run the analysis");
  act(() => buttonIn(pinnedBar(), "Open settings").click());
  expect(projectSettings()).not.toBeNull();
  expect(document.activeElement).toBe(voxelSizeField());
  expect(projectSettings()!.querySelector('[data-setting="voxel_size"] .setting-error')).not.toBeNull();
});

test("without a weather file Run analysis names Settings, with a button that opens it on the weather file's Import", async () => {
  service = new FakeService(NOTHING_RUN, null);
  const opened = project(NOTHING_RUN);
  await openWorkspace(service, { ...opened, inputs: { ...opened.inputs, weather: [] }, weather_location: null, weather_latitude: null });
  expect(settingsButton().title.startsWith("No weather file. North 0")).toBe(true);
  openStep("Criteria");
  const run = buttonIn(pinnedBar(), "Run analysis");
  expect(run.disabled).toBe(true);
  expect(reasonOf(run)).toBe("Add a weather file in Settings to run this mode");
  act(() => buttonIn(pinnedBar(), "Open settings").click());
  expect(projectSettings()).not.toBeNull();
  const addFiles = settingsWeatherBox()!.querySelector<HTMLButtonElement>(".input-box-title-row button")!;
  expect(addFiles.textContent).toBe("Import");
  expect(document.activeElement).toBe(addFiles);
  closeProjectSettings();
  await addWeatherFileInSettings();
  expect(buttonIn(pinnedBar(), "Run analysis").disabled).toBe(false);
  expect(pinnedBar().textContent).not.toContain("Add a weather file");
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
  act(() => buttonIn(container(), "Go to steepest slope of the envelope").click());
  expect(panelSectionOpen("Carving rule")).toBe(true);
  expect(container().querySelector('[data-setting="max_slope_deg"]')!.contains(document.activeElement)).toBe(true);
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
  expect(buildPart("Building massing").querySelector(".envelope-results-out-of-date")!.textContent).toContain("Out of date for the current settings");
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
  type(voxelSizeField(), "2");
  closeProjectSettings();
  const lockReason = "Settings changed: run the analysis again before building";
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

  openProjectSettings();
  service.stages = { preprocessing: "out_of_date", thresholding: "out_of_date", exporting: "out_of_date", massing: "out_of_date" };
  type(voxelSizeField(), "2");
  await waitForTheSave();
  await settle();
  closeProjectSettings();
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
  expect(stepIsOpen("Envelope and massing")).toBe(true);
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
  expect(stepIsOpen("Criteria")).toBe(true);
  expect(stepIsOpen("Site")).toBe(false);
  expect(FakeViewerScene.latest!.visibleLayers.has("test_surfaces")).toBe(true);
  expect(FakeViewerScene.latest!.visibleLayers.has("max_volume")).toBe(true);         // the layers of Criteria, the maximum volume as a ghost
  openStep("Export");
  expect(stepsReported).toHaveBeenLastCalledWith({ open: "export", view: "export", criteria: { shows: "editor", criterionId: "1" } });      // the one criterion's editor
  expect(FakeViewerScene.latest!.visibleLayers.has("max_volume")).toBe(false);
});

test("the Criteria step shows the kept voxels and starts with the carved ones hidden", async () => {
  await openChain([FACADES], undefined, (chain) => { chain.scorePointsOf = { "1": packScorePoints([0, 1, 2, 3], [1, 0, 1, 1]) }; });
  expect(FakeViewerScene.latest!.layers.get("carved_voxels")).toBeTruthy();         // drawn, so hidden by the step and not for want of data
  expect(FakeViewerScene.latest!.visibleLayers.has("kept_voxels")).toBe(true);
  expect(FakeViewerScene.latest!.visibleLayers.has("carved_voxels")).toBe(false);
});

test("the saver of the open project waits for an upload in flight, so a rename, reset or delete comes after it", async () => {
  service = new FakeService(CARVED, CARVING);
  let answerUpload: () => void = () => {};
  service.uploadsAnswerWhen = new Promise((resolve) => { answerUpload = resolve; });
  let saver: OpenProjectSettingsSaver | null = null;
  await openWorkspace(service, project(CARVED), { onSettingsSaverReady: (ready) => { saver = ready; } });
  const maximumVolumeBox = [...container().querySelectorAll<HTMLElement>(".input-box")].find((box) => box.querySelector("h3")?.textContent === "Maximum volume")!;
  const maximumVolumePicker = maximumVolumeBox.querySelector<HTMLInputElement>('input[type="file"]')!;
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

// The carving's reruns follow the project's switch in Settings > Carving (the stamp's run is in ProjectWorkspace.chain_runs).

/** The switch "Update the carving as I change its settings", in the project settings window (opened first when it is closed). */
const carvingUpdatesSwitch = () => (openProjectSettings(),
  projectSettings()!.querySelector<HTMLInputElement>('[data-setting="carving_updates_itself"] input[role="switch"]')!);

test("Settings has a Carving group whose switch is on by default; switched off, a threshold change starts no carving run; on again, it does", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  const group = () => projectSettings()!.querySelector<HTMLElement>('[data-setting="carving_updates_itself"]')!;
  expect(carvingUpdatesSwitch().checked).toBe(true);
  expect(group().querySelector(".setting-group-title")!.textContent).toBe("Carving");
  expect(group().querySelector(".switch-row")!.textContent).toBe("Update the carving as I change its settings");
  expect(group().querySelector(".setting-note")!.textContent).toContain("Update carving does");

  await act(async () => carvingUpdatesSwitch().click());
  await settle();
  expect(service.carvingUpdateChoices).toEqual([{ on: false }]);
  expect(carvingUpdatesSwitch().checked).toBe(false);
  closeProjectSettings();
  if (!stepIsOpen("Criteria")) openStep("Criteria");
  service.stages = { ...CARVED, thresholding: "out_of_date" };       // as the service holds it after the save
  typeAndLeave(thresholdField(), "2");
  await waitForTheSave();
  await settle();
  expect(service.savedValues.map(thresholdOf)).toEqual([2]);         // stored, not run
  expect(service.runsStarted).toEqual([]);
  expect(buttonIn(pinnedBar(), "Update carving")).toBeDefined();    // the pinned bar offers the run
  service.stages = CARVED;

  const switchAgain = carvingUpdatesSwitch();           // the window opened outside the act of the press
  await act(async () => switchAgain.click());
  await settle();
  expect(service.carvingUpdateChoices).toEqual([{ on: false }, { on: true }]);
  closeProjectSettings();
  typeAndLeave(thresholdField(), "3");
  await settle();
  expect(service.runsStarted).toEqual([["thresholding"]]);
});

test("a project stored with the switch off opens with it off and sends nothing", async () => {
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, { ...project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }), carving_updates_itself: false });
  expect(carvingUpdatesSwitch().checked).toBe(false);
  expect(service.count("PUT /carving-updates")).toBe(0);
});

test("the choice an earlier version kept in this browser is used, moved into the project once and forgotten here", async () => {
  window.localStorage.setItem("usc.autoUpdate.p", "off");
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED, { threshold: { method: "cutoff", value: 1.5 } }));
  expect(service.carvingUpdateChoices).toEqual([{ on: false }]);
  expect(window.localStorage.getItem("usc.autoUpdate.p")).toBeNull();
  expect(carvingUpdatesSwitch().checked).toBe(false);
  closeProjectSettings();
  if (!stepIsOpen("Criteria")) openStep("Criteria");
  typeAndLeave(thresholdField(), "2");
  await waitForTheSave();
  await settle();
  expect(service.runsStarted).toEqual([]);
  expect(service.count("PUT /carving-updates")).toBe(1);
});

test("a choice kept in this browser that the project already holds is forgotten here and not sent", async () => {
  window.localStorage.setItem("usc.autoUpdate.p", "on");
  service = new FakeService(CARVED, CARVING);
  await openWorkspace(service, project(CARVED));
  expect(service.count("PUT /carving-updates")).toBe(0);
  expect(window.localStorage.getItem("usc.autoUpdate.p")).toBeNull();
  expect(carvingUpdatesSwitch().checked).toBe(true);
});
