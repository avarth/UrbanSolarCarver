import { expect, test } from "vitest";
import { dayAndMonth, listedWithAnd, messages, plainText } from "./messages";

test("interface messages follow the copy rules", () => {
  const text = JSON.stringify(Object.values(messages).map(m => typeof m === "function" ? (m as (...values: number[]) => unknown)(1, 2, 3, 4) : m));
  expect(text).not.toMatch(/plates?\b|floor plate|—|NVIDIA/i);
  expect(text).toContain("No CUDA-enabled GPU found. USC runs on the CPU, which is slower.");
  expect(messages.fixSettingToRun("Voxel size")).toBe("Fix the voxel size to run the analysis.");
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
