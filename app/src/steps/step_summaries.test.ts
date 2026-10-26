import { expect, test } from "vitest";
import { STEP_NAMES, stepMark, stepNotUsableYet, stepSummary, type PipelineStage, type ProjectViewState, type StageState, type StepName } from "./step_summaries";

const THIN = "\u202f";
const NBSP = "\u00a0";

interface StateOverrides {
  maxVolume?: number;
  weather?: boolean;
  context?: number;
  terrain?: number;
  mode?: string;
  north?: number;
  voxelSize?: number;
  settingsToFix?: Partial<Record<StepName, number>>;
  keptPercent?: number;
  totalFloorArea?: number;
  storeys?: number;
  stages?: Partial<Record<PipelineStage, StageState>>;
}

function stateWith(overrides: StateOverrides): ProjectViewState {
  return {
    maxVolumeFiles: overrides.maxVolume ?? 1,
    hasWeatherFile: overrides.weather ?? false,
    contextFiles: overrides.context ?? 0,
    terrainFiles: overrides.terrain ?? 0,
    mode: overrides.mode ?? "time-based",
    northDegrees: overrides.north ?? 0,
    voxelSize: overrides.voxelSize ?? 1,
    settingsToFix: overrides.settingsToFix ?? {},
    keptPercent: overrides.keptPercent ?? null,
    totalFloorArea: overrides.totalFloorArea ?? null,
    storeys: overrides.storeys ?? null,
    stages: { preprocessing: "missing", thresholding: "missing", exporting: "missing", massing: "missing", ...overrides.stages },
  };
}

test("the steps are Inputs, Site and grid, Criteria, Envelope and massing and Export", () => {
  expect(STEP_NAMES).toEqual(["inputs", "site_and_grid", "criteria", "envelope_and_massing", "export"]);
});

test("closed steps summarise their state in the UX spec's words", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, weather: true }))).toBe("1 volume, weather");
  expect(stepSummary("envelope_and_massing", stateWith({ totalFloorArea: 4820, storeys: 7, stages: { exporting: "current", massing: "current" } })))
    .toBe(`4${THIN}820${NBSP}m², 7 storeys`);
  expect(stepSummary("envelope_and_massing", stateWith({ stages: { exporting: "out_of_date", massing: "out_of_date" } }))).toBe("Out of date");
});

test("the inputs summary counts the site's files per role and names a missing maximum volume", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 2 }))).toBe("2 volumes");
  expect(stepSummary("inputs", stateWith({ maxVolume: 0 }))).toBe("Maximum volume missing");
  expect(stepSummary("inputs", stateWith({ maxVolume: 0, weather: true }))).toBe("Maximum volume missing");
});

test("the site and grid summary gives the north and the voxel size, or the count of settings to fix", () => {
  expect(stepSummary("site_and_grid", stateWith({ north: 10, voxelSize: 0.5 }))).toBe(`North 10°, 0.5${NBSP}m voxels`);
  expect(stepSummary("site_and_grid", stateWith({}))).toBe(`North 0°, 1${NBSP}m voxels`);
  expect(stepSummary("site_and_grid", stateWith({ north: 12.5, voxelSize: 2 }))).toBe(`North 12.5°, 2${NBSP}m voxels`);
  expect(stepSummary("site_and_grid", stateWith({ settingsToFix: { site_and_grid: 1 } }))).toBe("1 setting to fix");
});

test("the criteria summary of one criterion joins its mode and its carving", () => {
  expect(stepSummary("criteria", stateWith({ mode: "benefit", keptPercent: 56.2, stages: { thresholding: "current" } }))).toBe(`Solar usefulness, 56${NBSP}% kept`);
  expect(stepSummary("criteria", stateWith({ mode: "daylight", keptPercent: 56.2, stages: { thresholding: "out_of_date" } }))).toBe("Daylight, Out of date");
  expect(stepSummary("criteria", stateWith({ mode: "radiative_cooling" }))).toBe("Night cooling, Not run yet");
  expect(stepSummary("criteria", stateWith({ stages: { thresholding: "out_of_date" } }))).toBe("Solar time-based, Out of date");     // no run summary read
  expect(stepSummary("criteria", stateWith({ settingsToFix: { criteria: 2 } }))).toBe("2 settings to fix");
});

test("the envelope and export summaries follow the stage status", () => {
  expect(stepSummary("envelope_and_massing", stateWith({}))).toBe("Not built yet");
  expect(stepSummary("export", stateWith({ stages: { exporting: "current", massing: "current" } }))).toBe("Ready");
  expect(stepSummary("export", stateWith({}))).toBe("Not built yet");
});

test("the export summary says out of date, not ready, while a built part is out of date", () => {
  const summaryOf = (exporting: StageState, massing: StageState) => stepSummary("export", stateWith({ stages: { exporting, massing } }));
  expect(summaryOf("out_of_date", "out_of_date")).toBe("Out of date");
  expect(summaryOf("out_of_date", "current")).toBe("Out of date");
  expect(summaryOf("current", "out_of_date")).toBe("Out of date");
  expect(summaryOf("out_of_date", "missing")).toBe("Out of date");
  expect(summaryOf("missing", "out_of_date")).toBe("Out of date");
});

test("the envelope and massing summary names what exists of the two parts (R2 5)", () => {
  const summaryOf = (exporting: StageState, massing: StageState) =>
    stepSummary("envelope_and_massing", stateWith({ totalFloorArea: 4820, storeys: 7, stages: { exporting, massing } }));
  expect(summaryOf("current", "missing")).toBe("Envelope built, massing not built");
  expect(summaryOf("missing", "current")).toBe("Envelope not built, massing built");
  expect(summaryOf("out_of_date", "current")).toBe("Envelope out of date, massing built");
  expect(summaryOf("current", "out_of_date")).toBe("Envelope built, massing out of date");
  expect(summaryOf("out_of_date", "missing")).toBe("Envelope out of date, massing not built");
  expect(summaryOf("missing", "out_of_date")).toBe("Envelope not built, massing out of date");
  // Both built and current: the numbers of the massing; without them (no run summary read) the words.
  expect(summaryOf("current", "current")).toBe(`4${THIN}820${NBSP}m², 7 storeys`);
  expect(stepSummary("envelope_and_massing", stateWith({ stages: { exporting: "current", massing: "current" } }))).toBe("Envelope built, massing built");
});

test("Export can be used once either part is built, and says which is ready", () => {
  expect(stepNotUsableYet("export", stateWith({}))).toBe("Build the envelope or the massing to export them");
  expect(stepNotUsableYet("export", stateWith({ stages: { exporting: "current" } }))).toBeNull();
  expect(stepNotUsableYet("export", stateWith({ stages: { massing: "out_of_date" } }))).toBeNull();
  expect(stepSummary("export", stateWith({ stages: { exporting: "current" } }))).toBe("Envelope ready");
  expect(stepSummary("export", stateWith({ stages: { massing: "current" } }))).toBe("Massing ready");
});

test("Criteria can always be used, as it holds the mode and Run analysis; Envelope and massing waits for an analysis", () => {
  expect(stepNotUsableYet("criteria", stateWith({}))).toBeNull();
  expect(stepNotUsableYet("site_and_grid", stateWith({}))).toBeNull();
  expect(stepNotUsableYet("envelope_and_massing", stateWith({}))).toBe("Run the analysis in Criteria before building the envelope and massing");
  expect(stepNotUsableYet("envelope_and_massing", stateWith({ stages: { thresholding: "out_of_date" } }))).toBeNull();
});

test("each step's mark: done, a setting to fix, or nothing yet", () => {
  expect(stepMark("inputs", stateWith({}))).toBe("done");
  expect(stepMark("inputs", stateWith({ maxVolume: 0 }))).toBe("none");
  expect(stepMark("site_and_grid", stateWith({ stages: { preprocessing: "current" } }))).toBe("done");
  expect(stepMark("site_and_grid", stateWith({}))).toBe("none");
  expect(stepMark("site_and_grid", stateWith({ settingsToFix: { site_and_grid: 2 }, stages: { preprocessing: "current" } }))).toBe("error");
  expect(stepMark("criteria", stateWith({ stages: { preprocessing: "current", thresholding: "current" } }))).toBe("done");
  expect(stepMark("criteria", stateWith({ stages: { thresholding: "out_of_date" } }))).toBe("none");
  expect(stepMark("envelope_and_massing", stateWith({ stages: { exporting: "current", massing: "current" } }))).toBe("done");
});

test("a setting to fix is counted and marked on the step that holds it", () => {
  const state = stateWith({ settingsToFix: { criteria: 1, envelope_and_massing: 2 },
                            stages: { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" } });
  expect(stepSummary("criteria", state)).toBe("1 setting to fix");
  expect(stepMark("criteria", state)).toBe("error");
  expect(stepSummary("envelope_and_massing", state)).toBe("2 settings to fix");
  expect(stepMark("envelope_and_massing", state)).toBe("error");
  expect(stepSummary("site_and_grid", state)).toBe(`North 0°, 1${NBSP}m voxels`);
  expect(stepMark("site_and_grid", state)).toBe("done");
  expect(stepMark("export", stateWith({ settingsToFix: { export: 1 } }))).toBe("error");
  expect(stepSummary("export", stateWith({ settingsToFix: { export: 1 } }))).toBe("1 setting to fix");
});

test("the inputs summary counts the surroundings files and names the terrain when there are some", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, context: 3 }))).toBe("1 volume, 3 surroundings files");
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, context: 1, terrain: 1, weather: true }))).toBe("1 volume, 1 surroundings file, terrain, weather");
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, terrain: 2 }))).toBe("1 volume, terrain");
});
