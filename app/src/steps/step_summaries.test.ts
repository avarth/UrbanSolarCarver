import { expect, test } from "vitest";
import { stepMark, stepNotUsableYet, stepSummary, type PipelineStage, type ProjectViewState, type StageState, type StepName } from "./step_summaries";

const THIN = "\u202f";
const NBSP = "\u00a0";

interface StateOverrides {
  maxVolume?: number;
  testSurfaces?: number;
  weather?: boolean;
  context?: number;
  terrain?: number;
  mode?: string;
  analysisPeriod?: ProjectViewState["analysisPeriod"];
  voxelSize?: number;
  settingsToFix?: Partial<Record<StepName, number>>;
  keptPercent?: number;
  totalFloorArea?: number;
  storeys?: number;
  stages?: Partial<Record<PipelineStage, StageState>>;
}

const DECEMBER_21_10_TO_14 = { startMonth: 12, startDay: 21, startHour: 10, endMonth: 12, endDay: 21, endHour: 14 };

function stateWith(overrides: StateOverrides): ProjectViewState {
  return {
    maxVolumeFiles: overrides.maxVolume ?? 1,
    testSurfaceFiles: overrides.testSurfaces ?? 1,
    hasWeatherFile: overrides.weather ?? false,
    contextFiles: overrides.context ?? 0,
    terrainFiles: overrides.terrain ?? 0,
    mode: overrides.mode ?? "time-based",
    analysisPeriod: overrides.analysisPeriod === undefined ? DECEMBER_21_10_TO_14 : overrides.analysisPeriod,
    voxelSize: overrides.voxelSize ?? 1,
    settingsToFix: overrides.settingsToFix ?? {},
    keptPercent: overrides.keptPercent ?? null,
    totalFloorArea: overrides.totalFloorArea ?? null,
    storeys: overrides.storeys ?? null,
    stages: { preprocessing: "missing", thresholding: "missing", exporting: "missing", massing: "missing", ...overrides.stages },
  };
}

test("closed steps summarise their state in the UX spec's words", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, testSurfaces: 2, weather: true }))).toBe("1 volume, 2 test surfaces, weather");
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, testSurfaces: 0 }))).toBe("Test surfaces missing");
  expect(stepSummary("envelope_and_massing", stateWith({ totalFloorArea: 4820, storeys: 7, stages: { exporting: "current", massing: "current" } })))
    .toBe(`4${THIN}820${NBSP}m², 7 storeys`);
  expect(stepSummary("envelope_and_massing", stateWith({ stages: { exporting: "out_of_date", massing: "out_of_date" } }))).toBe("Out of date");
});

test("a new project's Mode summary names its starting mode", () => {
  expect(stepSummary("mode", stateWith({ mode: "time-based" }))).toBe("Solar time-based");
  expect(stepSummary("mode", stateWith({ mode: "radiative_cooling" }))).toBe("Night cooling");
});

test("the inputs summary counts files per role and names what is missing", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 2, testSurfaces: 1 }))).toBe("2 volumes, 1 test surface");
  expect(stepSummary("inputs", stateWith({ maxVolume: 0, testSurfaces: 3 }))).toBe("Maximum volume missing");
  expect(stepSummary("inputs", stateWith({ maxVolume: 0, testSurfaces: 0, weather: true }))).toBe("Maximum volume and test surfaces missing");
});

test("the settings summary gives the period and the voxel size, or the count of settings to fix", () => {
  expect(stepSummary("settings", stateWith({}))).toBe(`21 Dec, 10 to 14\u00a0h; 1${NBSP}m voxels`);
  expect(stepSummary("settings", stateWith({ voxelSize: 0.5, analysisPeriod: { startMonth: 10, startDay: 15, startHour: 7, endMonth: 4, endDay: 15, endHour: 19 } })))
    .toBe(`15 Oct to 15 Apr, 7 to 19${NBSP}h; 0.5${NBSP}m voxels`);
  expect(stepSummary("settings", stateWith({ mode: "daylight", analysisPeriod: null, voxelSize: 2 }))).toBe(`2${NBSP}m voxels`);
  expect(stepSummary("settings", stateWith({ settingsToFix: { settings: 1 } }))).toBe("1 setting to fix");
});

test("the carving, envelope and export summaries follow the stage status", () => {
  expect(stepSummary("carving", stateWith({}))).toBe("Not run yet");
  expect(stepSummary("carving", stateWith({ keptPercent: 61.2, stages: { thresholding: "current" } }))).toBe(`61${NBSP}% kept`);
  expect(stepSummary("carving", stateWith({ keptPercent: 61.2, stages: { thresholding: "out_of_date" } }))).toBe("Out of date");
  expect(stepSummary("carving", stateWith({ stages: { thresholding: "out_of_date" } }))).toBe("Out of date");     // no run summary read
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

test("each step's mark: done, a setting to fix, or nothing yet", () => {
  expect(stepMark("inputs", stateWith({}))).toBe("done");
  expect(stepMark("inputs", stateWith({ testSurfaces: 0 }))).toBe("none");
  expect(stepMark("mode", stateWith({}))).toBe("done");
  expect(stepMark("settings", stateWith({ stages: { preprocessing: "current" } }))).toBe("done");
  expect(stepMark("settings", stateWith({ settingsToFix: { settings: 2 }, stages: { preprocessing: "current" } }))).toBe("error");
  expect(stepMark("carving", stateWith({ stages: { thresholding: "out_of_date" } }))).toBe("none");
  expect(stepMark("envelope_and_massing", stateWith({ stages: { exporting: "current", massing: "current" } }))).toBe("done");
});

test("a setting to fix is counted and marked on the step that holds it", () => {
  const state = stateWith({ settingsToFix: { carving: 1, envelope_and_massing: 2 },
                            stages: { preprocessing: "current", thresholding: "current", exporting: "current", massing: "current" } });
  expect(stepSummary("carving", state)).toBe("1 setting to fix");
  expect(stepMark("carving", state)).toBe("error");
  expect(stepSummary("envelope_and_massing", state)).toBe("2 settings to fix");
  expect(stepMark("envelope_and_massing", state)).toBe("error");
  expect(stepSummary("settings", state)).toBe("21 Dec, 10 to 14 h; 1 m voxels");
  expect(stepMark("settings", state)).toBe("done");
  expect(stepMark("export", stateWith({ settingsToFix: { export: 1 } }))).toBe("error");
  expect(stepSummary("export", stateWith({ settingsToFix: { export: 1 } }))).toBe("1 setting to fix");
});

test("the inputs summary counts the surroundings files and names the terrain when there are some", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, testSurfaces: 2, context: 3 }))).toBe("1 volume, 2 test surfaces, 3 surroundings files");
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, testSurfaces: 1, context: 1, terrain: 1, weather: true })))
    .toBe("1 volume, 1 test surface, 1 surroundings file, terrain, weather");
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, testSurfaces: 1, terrain: 2 }))).toBe("1 volume, 1 test surface, terrain");
});
