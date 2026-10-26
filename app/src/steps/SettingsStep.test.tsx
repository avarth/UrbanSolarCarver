import { readFileSync } from "node:fs";
import { act, useReducer } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, type ModeInfo } from "../api_client/client";
import { formReducer, initialFormState, type FormState } from "../settings_form/form_state";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import type { SaveOutcome } from "../settings_form/form_state";
import {
  runAnalysisAfterSaving, runAnalysisBlocker, SaveFailureNotice, saveFailureTextOf, SettingsStep, SettingsToFix, settingsToFixByStep, settingsToFixCount,
  type RunAnalysisConditions,
} from "./SettingsStep";

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
  { name: "time-based", description: "", needs_epw: true, needs_period: true, experimental: false, score_kind: "violation_count", weight_unit: "", score_unit: "",
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

/** The settings of a criterion among those these tests name (GET criterion-keys gives the engine's list). */
const CRITERION_KEYS: ReadonlySet<string> = new Set(["mode", "start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour", "threshold",
                                                    "carve_fraction", "max_slope_deg"]);

/** The conditions of the Run analysis pinned in Site and grid. */
function conditions(overrides: Partial<RunAnalysisConditions> = {}): RunAnalysisConditions {
  return { runActive: false, maxVolumeFiles: 1, testSurfaceFiles: 2, modeNeedsWeatherFile: true, hasWeatherFile: true, form: form(),
           warmUpState: "ready", criterionKeys: CRITERION_KEYS, shownIn: "site_and_grid", ...overrides };
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
  expect(runAnalysisBlocker(conditions({ form: rejected([{ field: "end_day", message: "no such day" }]) })))
    .toBe("Fix the analysis period in Criteria to run the analysis.");
  expect(runAnalysisBlocker(conditions({ form: rejected([{ field: null, message: "Value error, ray_batch_size must be larger than voxel_size" }]) })))
    .toBe("Fix the rays per batch to run the analysis.");
  expect(runAnalysisBlocker(conditions({ form: rejected([{ field: null, message: "Value error, the settings do not fit together" }]) })))
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
  // No grid line: only the sample spacing line stays.
  expect([...rendered.container.querySelectorAll(".setting-note")].map((note) => note.textContent)).toEqual(["Test surfaces sampled every 0.5 m"]);
});

test("a message that names no setting is shown for the step; during a run the fields are disabled with the reason", () => {
  rendered = renderForTest(<SettingsStep form={rejected([{ field: null, message: "Value error, the settings do not fit together" }])} onChange={() => {}}
                                         disabledReason="A run is in progress" />);
  expect(rendered.container.querySelector(".step-error")!.textContent).toBe("The settings do not fit together");
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

test("a save that failed without field errors is said in the panel with Save again; a stopped engine or lost token is left to the overlay", () => {
  expect(saveFailureTextOf(null)).toBeNull();
  expect(saveFailureTextOf(new TypeError("Failed to fetch"))).toBeNull();
  expect(saveFailureTextOf(new ApiError(401, { detail: "The access token is missing or wrong." }))).toBeNull();
  expect(saveFailureTextOf(new ApiError(409, { detail: "A run of project 'p' is active." })))
    .toEqual({ reason: "A run of this project is in progress, perhaps in another tab.", advice: "Save again once it has ended." });
  expect(saveFailureTextOf(new ApiError(500, "Internal Server Error")))
    .toEqual({ reason: null, advice: "Save again, or start a run: it saves the settings first." });
  expect(saveFailureTextOf(new ApiError(422, { detail: [{ loc: ["body", "values"], msg: "Field required" }] }))!.reason).toBeNull();

  const onSaveAgain = vi.fn();
  rendered = renderForTest(<SaveFailureNotice text={saveFailureTextOf(new ApiError(409, { detail: "x" }))!} onSaveAgain={onSaveAgain} />);
  const notice = rendered.container.querySelector("[role=alert]")!;
  expect(notice.textContent).toBe("The last change to the settings was not saved." +
    "A run of this project is in progress, perhaps in another tab. Save again once it has ended.Save again");
  click(notice.querySelector("button")!);
  expect(onSaveAgain).toHaveBeenCalledOnce();
});

test("Run analysis starts the run only after the waiting change was saved, or when nothing waited", async () => {
  for (const [outcome, starts] of [["saved", true], ["none", true], ["refused", false], ["failed", false], ["overtaken", false]] as [SaveOutcome, boolean][]) {
    const startRun = vi.fn();
    expect(await runAnalysisAfterSaving(async () => outcome, startRun)).toBe(starts);
    expect(startRun).toHaveBeenCalledTimes(starts ? 1 : 0);
  }
});

test("an error of the whole config outlines the settings it names, opens their fold, and leaves the grid line under Voxel size", () => {
  const fieldOf = (label: string) => [...rendered!.container.querySelectorAll(".setting-field")].find((field) => field.textContent!.startsWith(label))!;
  const crossFieldError = { field: null, message: "Value error, ray_batch_size (1) must be larger than voxel_size (1 m)" };
  // A refusal of the stored voxel size (another setting changed): the grid line is the one of that voxel size.
  rendered = renderForTest(<SettingsStep form={rejected([crossFieldError])} onChange={() => {}} disabledReason={null} />);
  expect(rendered.container.querySelector(".step-error")).toBeNull();
  expect(fieldOf("Voxel size").querySelector("input")!.getAttribute("aria-invalid")).toBe("true");
  expect(fieldOf("Voxel size").querySelector(".setting-error")!.textContent).toContain("must be larger than voxel size");
  expect(fieldOf("Voxel size").querySelector(".setting-note")!.textContent).toBe("62 voxels per side, 238 328 in total");
  expect(fieldOf("Rays per batch").querySelector("input")!.getAttribute("aria-invalid")).toBe("true");
  // A refused voxel size: the line says it is the grid of the voxel size last saved.
  const refusedVoxelSize = formReducer(formReducer(form(), { type: "values_changed", values: { voxel_size: 0.5 } }),
    { type: "save_rejected", reply: { field_errors: [crossFieldError], grid_plan: null } });
  rendered.rerender(<SettingsStep form={refusedVoxelSize} onChange={() => {}} disabledReason={null} />);
  expect(fieldOf("Voxel size").querySelector(".setting-note")!.textContent)
    .toBe("Grid at the saved voxel size of 1 m: 62 voxels per side, 238 328 in total");
});

test("the settings to fix are counted by the step whose field holds them; messages for no field count where their form's settings are", () => {
  const criterion = rejected([{ field: "max_slope_deg", message: "Input should be greater than 0" },
                              { field: "start_day", message: "a" }, { field: "end_day", message: "b" },
                              { field: null, message: "Value error, the settings do not fit together" }]);
  const shared = rejected([{ field: "voxel_size", message: "too many voxels" }, { field: "min_plate_dimension", message: "Input should be greater than 0" }]);
  // The period and the slope limit (one each) and the message for no field are the criterion's; the voxel size is Site and grid's.
  expect(settingsToFixByStep(shared, criterion, CRITERION_KEYS)).toEqual({ criteria: 3, site_and_grid: 1, envelope_and_massing: 1 });
  expect(settingsToFixByStep(criterion, form(), CRITERION_KEYS)).toEqual({ criteria: 2, site_and_grid: 1 });
  expect(settingsToFixCount(criterion)).toBe(3);
});

test("a step that cannot be used yet still shows its settings to fix, so they can be fixed", () => {
  const state = rejected([{ field: "max_slope_deg", message: "Input should be greater than 0" }]);
  const onChange = vi.fn();
  rendered = renderForTest(<SettingsToFix step="carving" form={state} onChange={onChange} disabledReason={null} />);
  const field = rendered.container.querySelector<HTMLElement>('[data-setting="max_slope_deg"]')!;
  expect(field.querySelector(".setting-error")!.textContent).toBe("Input should be greater than 0");
  expect(rendered.container.querySelectorAll(".setting-field")).toHaveLength(1);
  rendered.rerender(<SettingsToFix step="envelope_and_massing" form={state} onChange={onChange} disabledReason={null} />);
  expect(rendered.container.querySelector(".setting-field")).toBeNull();
});

test("a setting to fix in another step is named with that step under the run button", () => {
  const slopeRefused = rejected([{ field: "max_slope_deg", message: "Input should be greater than 0" }]);
  expect(runAnalysisBlocker(conditions({ form: slopeRefused }))).toBe("Fix the steepest step between columns in Criteria to run the analysis.");
  expect(runAnalysisBlocker(conditions({ form: slopeRefused, shownIn: "criteria" }))).toBe("Fix the steepest step between columns to run the analysis.");
  const voxelSizeRefused = rejected([{ field: "voxel_size", message: "too many voxels" }], PLAN_OVER_BUDGET);
  expect(runAnalysisBlocker(conditions({ form: voxelSizeRefused, shownIn: "criteria" }))).toBe("Fix the voxel size in Site and grid to run the analysis.");
  const marginRefused = rejected([{ field: "min_plate_dimension", message: "Input should be greater than 0" }]);
  expect(runAnalysisBlocker(conditions({ form: marginRefused, shownIn: "criteria" }))).toBe("Fix the grid module in Envelope and massing to run the analysis.");
});

test("Site and grid draws the shared settings and a criterion's panel its own, by the criterion keys", () => {
  rendered = renderForTest(<SettingsStep form={form()} onChange={() => {}} disabledReason={null} settingShown={(name) => !CRITERION_KEYS.has(name)} />);
  expect(rendered.container.querySelector('[data-setting="voxel_size"]')).not.toBeNull();
  expect(rendered.container.querySelector('[data-setting="start_month"]')).toBeNull();
  rendered.rerender(<SettingsStep form={form()} onChange={() => {}} disabledReason={null} settingShown={(name) => CRITERION_KEYS.has(name)} />);
  expect(rendered.container.querySelector('[data-setting="voxel_size"]')).toBeNull();
  expect(rendered.container.querySelector('[data-setting="start_month"]')).not.toBeNull();
});

/** The Settings step over the form the app holds, every change going to it as the app's onChange does. */
function SettingsStepWithItsForm({ start }: { start: FormState }) {
  const [state, dispatch] = useReducer(formReducer, start);
  return <SettingsStep form={state} onChange={(values) => dispatch({ type: "values_changed", values })} disabledReason={null} />;
}

function typeInto(field: HTMLInputElement, text: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const fieldNamed = (setting: string) => rendered!.container.querySelector<HTMLElement>(`[data-setting="${setting}"]`)!;
const notesUnder = (setting: string) => [...fieldNamed(setting).querySelectorAll(".setting-note")].map((note) => note.textContent);

test("under Voxel size a quiet line gives the sample spacing the engine uses, half the voxel size; there is no field for it", () => {
  rendered = renderForTest(<SettingsStepWithItsForm start={form()} />);
  expect(notesUnder("voxel_size")).toEqual(["62 voxels per side, 238\u202f328 in total", "Test surfaces sampled every 0.5\u00a0m"]);
  typeInto(fieldNamed("voxel_size").querySelector<HTMLInputElement>("input[type='number']")!, "0.25");
  expect(notesUnder("voxel_size")[1]).toBe("Test surfaces sampled every 0.125\u00a0m");
  expect(rendered.container.querySelector('[data-setting="grid_step"]')).toBeNull();
  expect(fieldNamed("voxel_size").querySelector("[role='status']")).toBeNull();      // nothing is lowered any more, so nothing to announce
});

test("the line keeps its place under an over-budget voxel size, and before the grid is planned", () => {
  rendered = renderForTest(<SettingsStep form={form(PLAN_OVER_BUDGET)} onChange={() => {}} disabledReason={null} />);
  expect(notesUnder("voxel_size")).toEqual(["Test surfaces sampled every 0.5\u00a0m"]);
  rendered.rerender(<SettingsStep form={initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "time-based" }, gridPlan: null })}
                                  onChange={() => {}} disabledReason={null} />);
  expect(notesUnder("voxel_size")).toEqual(["Test surfaces sampled every 0.5\u00a0m"]);
});

test("the sample spacing the line gives is the engine's rule for an unset grid_step", () => {
  const schemas = readFileSync("../src/urbansolarcarver/pydantic_schemas.py", "utf8");
  expect(schemas).toContain("GRID_STEP_PER_VOXEL_SIZE_WHEN_UNSET = 0.5");
  expect(schemas).toContain("None (default): half the voxel size.");
});

test("a project with surroundings shows Account for context blocking, on by default, and changing it reaches onChange", () => {
  const schema = { properties: { ...SCHEMA.properties, context_blocks_rays: { default: true, type: "boolean" } } };
  const withSwitch = initialFormState({ schema, modes: MODES, settings: { mode: "time-based" }, gridPlan: PLAN_WITHIN_BUDGET });
  const onChange = vi.fn();
  rendered = renderForTest(<SettingsStep form={withSwitch} onChange={onChange} disabledReason={null} inputRoles={["context"]} />);
  const field = [...rendered.container.querySelectorAll<HTMLElement>(".setting-field")]
    .find((candidate) => candidate.textContent!.startsWith("Account for context blocking"))!;
  const box = field.querySelector<HTMLInputElement>("input[type=checkbox]")!;
  expect(box.checked).toBe(true);
  click(box);
  expect(onChange).toHaveBeenLastCalledWith({ context_blocks_rays: false });
  rendered.unmount();
  rendered = renderForTest(<SettingsStep form={withSwitch} onChange={() => {}} disabledReason={null} />);
  expect(rendered.container.textContent).not.toContain("Account for context blocking");
});
