import { expect, test } from "vitest";
import { stepMark, stepSummary, type PipelineStage, type ProjectViewState, type StageState } from "./step_summaries";

const THIN = " ";
const NBSP = " ";

interface StateOverrides {
  maxVolume?: number;
  testSurfaces?: number;
  weather?: boolean;
  mode?: string;
  analysisPeriod?: ProjectViewState["analysisPeriod"];
  voxelSize?: number;
  settingsToFix?: number;
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
    mode: overrides.mode ?? "time-based",
    analysisPeriod: overrides.analysisPeriod === undefined ? DECEMBER_21_10_TO_14 : overrides.analysisPeriod,
    voxelSize: overrides.voxelSize ?? 1,
    settingsToFix: overrides.settingsToFix ?? 0,
    keptPercent: overrides.keptPercent ?? null,
    totalFloorArea: overrides.totalFloorArea ?? null,
    storeys: overrides.storeys ?? null,
    stages: { preprocessing: "missing", thresholding: "missing", exporting: "missing", massing: "missing", ...overrides.stages },
  };
}

test("closed steps summarise their state in the UX spec's words", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, testSurfaces: 2, weather: true }))).toBe("1 volume, 2 test surfaces, weather");
  expect(stepSummary("inputs", stateWith({ maxVolume: 1, testSurfaces: 0 }))).toBe("Test surfaces missing");
  expect(stepSummary("envelope_and_massing", stateWith({ totalFloorArea: 4820, storeys: 7, stages: { massing: "current" } }))).toBe(`4${THIN}820${NBSP}m², 7 storeys`);
  expect(stepSummary("envelope_and_massing", stateWith({ stages: { massing: "out_of_date" } }))).toBe("Out of date");
});

test("a new project's Mode summary names its starting mode", () => {
  expect(stepSummary("mode", stateWith({ mode: "time-based" }))).toBe("Sun at set hours");
  expect(stepSummary("mode", stateWith({ mode: "radiative_cooling" }))).toBe("Night cooling");
});

test("the inputs summary counts files per role and names what is missing", () => {
  expect(stepSummary("inputs", stateWith({ maxVolume: 2, testSurfaces: 1 }))).toBe("2 volumes, 1 test surface");
  expect(stepSummary("inputs", stateWith({ maxVolume: 0, testSurfaces: 3 }))).toBe("Maximum volume missing");
  expect(stepSummary("inputs", stateWith({ maxVolume: 0, testSurfaces: 0, weather: true }))).toBe("Maximum volume and test surfaces missing");
});

test("the settings summary gives the period and the voxel size, or the count of settings to fix", () => {
  expect(stepSummary("settings", stateWith({}))).toBe(`21 Dec, 10 to 14 h; 1${NBSP}m voxels`);
  expect(stepSummary("settings", stateWith({ voxelSize: 0.5, analysisPeriod: { startMonth: 10, startDay: 15, startHour: 7, endMonth: 4, endDay: 15, endHour: 19 } })))
    .toBe(`15 Oct to 15 Apr, 7 to 19 h; 0.5${NBSP}m voxels`);
  expect(stepSummary("settings", stateWith({ mode: "daylight", analysisPeriod: null, voxelSize: 2 }))).toBe(`2${NBSP}m voxels`);
  expect(stepSummary("settings", stateWith({ settingsToFix: 1 }))).toBe("1 setting to fix");
});

test("the carving, envelope and export summaries follow the stage status", () => {
  expect(stepSummary("carving", stateWith({}))).toBe("Not run yet");
  expect(stepSummary("carving", stateWith({ keptPercent: 61.2, stages: { thresholding: "current" } }))).toBe(`61${NBSP}% kept`);
  expect(stepSummary("carving", stateWith({ keptPercent: 61.2, stages: { thresholding: "out_of_date" } }))).toBe("Out of date");
  expect(stepSummary("envelope_and_massing", stateWith({}))).toBe("Not built yet");
  expect(stepSummary("envelope_and_massing", stateWith({ totalFloorArea: 4820, storeys: 7, stages: { exporting: "out_of_date", massing: "current" } }))).toBe("Out of date");
  expect(stepSummary("export", stateWith({ stages: { exporting: "current", massing: "current" } }))).toBe("Ready");
  expect(stepSummary("export", stateWith({ stages: { exporting: "current" } }))).toBe("Build the envelope first");
});

test("each step's mark: done, a setting to fix, or nothing yet", () => {
  expect(stepMark("inputs", stateWith({}))).toBe("done");
  expect(stepMark("inputs", stateWith({ testSurfaces: 0 }))).toBe("none");
  expect(stepMark("mode", stateWith({}))).toBe("done");
  expect(stepMark("settings", stateWith({ stages: { preprocessing: "current" } }))).toBe("done");
  expect(stepMark("settings", stateWith({ settingsToFix: 2, stages: { preprocessing: "current" } }))).toBe("error");
  expect(stepMark("carving", stateWith({ stages: { thresholding: "out_of_date" } }))).toBe("none");
  expect(stepMark("envelope_and_massing", stateWith({ stages: { exporting: "current", massing: "current" } }))).toBe("done");
});
