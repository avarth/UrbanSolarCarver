import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../api_client/client";
import { formReducer, initialFormState, type FormState } from "../settings_form/form_state";
import { renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { SaveOutcome } from "../settings_form/form_state";
import { runAnalysisAfterSaving, runAnalysisBlocker, SettingsStep, settingsToFixCount, type RunAnalysisConditions } from "./SettingsStep";

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

const SCHEMA = {
  properties: {
    mode: { default: "time-based", type: "string" },
    voxel_size: { default: 1.0, type: "number" },
    north_deg: { default: 0.0, type: "number" },
    start_month: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    start_day: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    start_hour: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_month: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_day: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_hour: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
  },
};
const MODES: ModeInfo[] = [
  { name: "time-based", description: "", needs_epw: true, needs_period: true, experimental: false, score_kind: "violation_count", weight_unit: "",
    starting_values: { start_month: 12, start_day: 21, start_hour: 10, end_month: 12, end_day: 21, end_hour: 14 } },
];
const PLAN_WITHIN_BUDGET = { resolution: 62, voxel_size: 1, total_voxels: 238328, extent: 62, budget_voxels: 500000000 };
const PLAN_OVER_BUDGET = { resolution: 884, voxel_size: 0.06, total_voxels: 690807104, extent: 53, budget_voxels: 500000000 };

function form(gridPlan = PLAN_WITHIN_BUDGET): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "time-based" }, gridPlan });
}

function rejected(fieldErrors: { field: string | null; message: string }[], gridPlan: typeof PLAN_OVER_BUDGET | null = null): FormState {
  return formReducer(form(), { type: "save_rejected", reply: { field_errors: fieldErrors, grid_plan: gridPlan } });
}

function conditions(overrides: Partial<RunAnalysisConditions> = {}): RunAnalysisConditions {
  return { runActive: false, maxVolumeFiles: 1, testSurfaceFiles: 2, modeNeedsWeatherFile: true, hasWeatherFile: true, form: form(),
           warmUpState: "ready", ...overrides };
}

test("Run analysis says what blocks it, in order: a run, the inputs, the weather file, a setting, the warm-up", () => {
  expect(runAnalysisBlocker(conditions())).toBeNull();
  expect(runAnalysisBlocker(conditions({ warmUpState: "cpu" }))).toBeNull();
  expect(runAnalysisBlocker(conditions({ warmUpState: "failed" }))).toBeNull();
  expect(runAnalysisBlocker(conditions({ runActive: true, testSurfaceFiles: 0 }))).toBe("A run is in progress");
  expect(runAnalysisBlocker(conditions({ testSurfaceFiles: 0, hasWeatherFile: false }))).toBe("Add test surfaces to run the analysis");
  expect(runAnalysisBlocker(conditions({ maxVolumeFiles: 0 }))).toBe("Add a maximum volume to run the analysis");
  expect(runAnalysisBlocker(conditions({ hasWeatherFile: false, warmUpState: "running" }))).toBe("Add a weather file to run this mode");
  expect(runAnalysisBlocker(conditions({ hasWeatherFile: false, modeNeedsWeatherFile: false }))).toBeNull();
  expect(runAnalysisBlocker(conditions({ form: rejected([{ field: "voxel_size", message: "too many voxels" }], PLAN_OVER_BUDGET) })))
    .toBe("Fix the voxel size to run the analysis.");
  expect(runAnalysisBlocker(conditions({ form: rejected([{ field: "end_day", message: "no such day" }]) }))).toBe("Fix the analysis period to run the analysis.");
  expect(runAnalysisBlocker(conditions({ form: rejected([{ field: null, message: "grid_step must be <= voxel_size" }]) })))
    .toBe("Fix the settings above to run the analysis.");
  expect(runAnalysisBlocker(conditions({ warmUpState: "running" }))).toBe("Waiting for the GPU to be ready");
  expect(runAnalysisBlocker(conditions({ warmUpState: null }))).toBe("Waiting for the GPU to be ready");
});

test("the settings to fix count field errors and step errors", () => {
  expect(settingsToFixCount(rejected([{ field: "voxel_size", message: "a" }, { field: null, message: "b" }]))).toBe(2);
});

test("the grid it gives sits under Voxel size", () => {
  rendered = renderForTest(<SettingsStep form={form()} onChange={() => {}} disabledReason={null} />);
  expect(rendered.container.querySelector(".setting-note")!.textContent).toBe("62 voxels per side, 238\u202f328 in total");
});

test("a grid over the budget: the voxel count, the budget and the size to use, in bold, under an outlined Voxel size", () => {
  rendered = renderForTest(<SettingsStep form={rejected([{ field: "voxel_size", message: "The voxel grid would have 884^3 voxels" }], PLAN_OVER_BUDGET)}
                                         onChange={() => {}} disabledReason={null} />);
  const error = rendered.container.querySelector(".setting-error")!;
  expect(error.textContent).toBe("This grid would have 884 voxels per side, 690\u202f807\u202f104 in total. The analysis can handle up to 500\u202f000\u202f000. Use 0.07\u00a0m or more.");
  expect(error.querySelector("strong")!.textContent).toBe("Use 0.07\u00a0m or more.");
  expect(error.querySelector("svg")).not.toBeNull();
  const voxelSize = [...rendered.container.querySelectorAll(".setting-field")].find((field) => field.textContent!.startsWith("Voxel size"))!;
  expect(voxelSize.querySelector("input")!.getAttribute("aria-invalid")).toBe("true");
  expect(rendered.container.querySelector(".setting-note")).toBeNull();
});

test("a message that names no setting is shown for the step; during a run the fields are disabled with the reason", () => {
  rendered = renderForTest(<SettingsStep form={rejected([{ field: null, message: "grid_step must be <= voxel_size" }])} onChange={() => {}}
                                         disabledReason="A run is in progress" />);
  expect(rendered.container.querySelector(".step-error")!.textContent).toBe("grid_step must be <= voxel_size");
  expect(rendered.container.textContent).toContain("A run is in progress");
  const fields = [...rendered.container.querySelectorAll<HTMLInputElement>("input")];
  expect(fields.length).toBeGreaterThan(0);
  expect(fields.every((field) => field.disabled)).toBe(true);
});

test("a project whose stored grid is over the budget opens with Voxel size to fix and Run analysis blocked", () => {
  const opened = form(PLAN_OVER_BUDGET);
  expect(settingsToFixCount(opened)).toBe(1);
  expect(runAnalysisBlocker(conditions({ form: opened }))).toBe("Fix the voxel size to run the analysis.");
  rendered = renderForTest(<SettingsStep form={opened} onChange={() => {}} disabledReason={null} />);
  expect(rendered.container.querySelector(".setting-error strong")!.textContent).toBe("Use 0.07\u00a0m or more.");
});

test("Run analysis starts the run only after the waiting change was saved, or when nothing waited", async () => {
  for (const [outcome, starts] of [["saved", true], ["none", true], ["refused", false], ["failed", false], ["overtaken", false]] as [SaveOutcome, boolean][]) {
    const startRun = vi.fn();
    expect(await runAnalysisAfterSaving(async () => outcome, startRun)).toBe(starts);
    expect(startRun).toHaveBeenCalledTimes(starts ? 1 : 0);
  }
});
