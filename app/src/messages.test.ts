import { expect, test } from "vitest";
import { dayAndMonth, listedWithAnd, messages, plainText } from "./messages";

test("interface messages follow the copy rules", () => {
  const text = JSON.stringify(Object.values(messages).map(m => typeof m === "function" ? (m as (...values: number[]) => unknown)(1, 2, 3, 4) : m));
  expect(text).not.toMatch(/plates?\b|floor plate|—|NVIDIA/i);
  expect(text).toContain("No CUDA-enabled GPU found. USC runs on the CPU, which is slower.");
  expect(messages.fixSettingToRun("Voxel size")).toBe("Fix the voxel size to run the analysis");
});

test("the reasons a run button or a carving change waits, which fill the same slots, end alike: one sentence has no final period", () => {
  const oneSentence = [
    messages.runInProgress, messages.addMaxVolumeToRun, messages.addTestSurfacesToRun, messages.addMaxVolumeAndTestSurfacesToRun,
    messages.addTestSurfacesOfCriterionToRun("Daylight"), messages.turnOnCriterionToRun, messages.fixSettingsToRun,
    messages.fixSettingsInStepToRun("Criteria"), messages.fixSettingToRun("Voxel size"), messages.fixSettingInStepToRun("Voxel size", "Site and grid"),
    messages.weatherFileNeeded, messages.weatherFileNeededFor("Daylight"), messages.runButtonWaitsForGpu, messages.carvingWaitsForAnalysisOf("Daylight"),
    messages.addTestSurfacesFirst("Daylight"), messages.fixSettingOfCriterionToRun("Voxel size", "Daylight"),
    messages.fixSettingsOfCriterionToRun("Daylight"), messages.buildWaitsForAnalysis, messages.buildWaitsForFirstAnalysis, messages.buildWaitsForCarving,
  ];
  for (const reason of oneSentence) expect(reason).toMatch(/^[^.]+[^.]$/);
});

test("the engine stopped and access lost messages show the command as code, without markdown backticks", () => {
  for (const parts of [messages.engineStopped, messages.accessLost]) {
    expect(plainText(parts)).not.toContain("`");
    expect(parts).toContainEqual({ code: "usc ui" });
  }
  expect(plainText(messages.engineStopped)).toBe("The USC engine stopped. Start it again with usc ui, then reload this page.");
});

test("the grid over budget message groups digits and gives the voxel size to use", () => {
  expect(messages.gridOverBudget(884, 690807104, 500000000, 0.07)).toEqual({
    description: "This grid would have 884 voxels per side, 690\u202f807\u202f104 in total. The analysis can handle up to 500\u202f000\u202f000.",
    advice: "Use 0.07\u00a0m or more.",
  });
});

test("the device lines of UX 5.1 and 6.1", () => {
  expect(messages.gpuPreparing).toBe("Preparing the GPU");
  expect(messages.gpuWarmUpHint).toBe("You can open a project and add files now. The run buttons wait until the GPU is ready.");
  expect(messages.gpuReadyWithDevice("RTX 4070")).toBe("GPU ready: RTX 4070");
  expect(messages.runButtonWaitsForGpu).toBe("Waiting for the GPU to be ready");
});

test("the count of settings to fix agrees with the number", () => {
  expect(messages.settingsToFix(1)).toBe("1 setting to fix");
  expect(messages.settingsToFix(3)).toBe("3 settings to fix");
});

test("dates and lists for the 3D view", () => {
  expect(dayAndMonth("12-21")).toBe("21 Dec");
  expect(listedWithAnd(["10", "12", "14"])).toBe("10, 12 and 14");
  expect(listedWithAnd(["21 Dec"])).toBe("21 Dec");
});

test("the notice of a new weather file names its location when the file has one", () => {
  expect(messages.weatherChangeColdPeriod("Brisbane, AUS", messages.periodDates(5, 3, 9, 20), messages.periodDates(9, 30, 5, 15)))
    .toBe("The new weather file (Brisbane, AUS) has its cold period from 3 May to 20 Sep; the analysis period is 30 Sep to 15 May.");
  expect(messages.weatherChangeColdPeriod(null, messages.periodDates(5, 3, 9, 20), messages.periodDates(9, 30, 5, 15)))
    .toBe("The new weather file has its cold period from 3 May to 20 Sep; the analysis period is 30 Sep to 15 May.");
  expect(messages.weatherChangeOtherHemisphere("Brisbane, AUS", "southern", "21 Jun, 10 to 14 h")).toBe(
    "The new weather file (Brisbane, AUS) is in the southern hemisphere: winter there is June to August. " +
    "Shift the analysis period by six months, to 21 Jun, 10 to 14 h?");
  expect(messages.weatherChangeOtherHemisphere(null, "northern", "21 Dec, 10 to 14 h")).toBe(
    "The new weather file is in the northern hemisphere: winter there is December to February. " +
    "Shift the analysis period by six months, to 21 Dec, 10 to 14 h?");
  expect(messages.periodDates(12, 21, 12, 22)).toBe("21 to 22 Dec");
});
