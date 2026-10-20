import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../../api_client/client";
import { renderForTest, type RenderedOverlay } from "../../viewer_overlays/render_for_test";
import { formReducer, initialFormState, type FormState } from "../form_state";
import { settingsForStep } from "../presentation";
import { SettingField } from "../SettingField";
import { SettingGroup } from "../SettingGroup";

// The engine's bounds of the settings these tests use, as GET schema gives them (pydantic_schemas.py).
const SCHEMA = {
  properties: {
    mode: { default: "daylight", type: "string" },
    voxel_size: { default: 1.0, type: "number", minimum: 0.01, maximum: 100 },
    grid_step: { default: 1.0, type: "number", exclusiveMinimum: 0 },
    score_smoothing: { anyOf: [{ type: "number", minimum: 0, maximum: 20 }, { type: "null" }], default: null },
    plate_tolerance: { default: 0.2, type: "number", minimum: 0, maximum: 1 },
    smooth_iters: { default: 2, type: "integer", minimum: 0, maximum: 6 },
    carve_above_min_consecutive: { default: 1, type: "integer", minimum: 1 },
    ray_batch_size: { default: 0, type: "integer", minimum: 0 },
    diagnostics: { default: false, type: "boolean" },
  },
};
const MODES: ModeInfo[] = [{ name: "daylight", description: "", needs_epw: false, needs_period: false, experimental: false,
                             score_kind: "weighted_sum", weight_unit: "", score_unit: "", starting_values: {} }];

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function form(settings: Record<string, unknown> = {}): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "daylight", ...settings }, gridPlan: null });
}

function viewOf(step: Parameters<typeof settingsForStep>[0], name: string) {
  return settingsForStep(step, "daylight").flatMap((group) => [...group.essential, ...group.folded]).find((view) => view.name === name)!;
}

/** Sets *text* as the value the way the browser does when the user types or drags, so React's change handler runs. */
function setValue(field: HTMLInputElement, text: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const slider = () => rendered!.container.querySelector<HTMLInputElement>("input[type='range']")!;
const numberField = () => rendered!.container.querySelector<HTMLInputElement>("input[type='number']")!;

test("a ranged setting has a slider over its practical range, labelled by the setting's label, beside its number field", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={viewOf("settings", "voxel_size")} form={form()} onChange={onChange} />);
  expect([slider().min, slider().max, slider().step, slider().value]).toEqual(["0.1", "5", "0.1", "1"]);
  const label = rendered.container.querySelector("label.setting-label")!;
  expect(slider().getAttribute("aria-labelledby")).toBe(label.id);
  expect(slider().getAttribute("aria-valuetext")).toBe("1 m");
  setValue(slider(), "2.5");
  expect(onChange).toHaveBeenLastCalledWith({ voxel_size: 2.5 });
  // The number field takes what the engine accepts outside the slider: 8 m is more than the slider's 5.
  setValue(numberField(), "8");
  expect(onChange).toHaveBeenLastCalledWith({ voxel_size: 8 });
});

test("a value outside the slider's range pins the handle at the end of the track, and is said in full to a screen reader", () => {
  rendered = renderForTest(<SettingField view={viewOf("settings", "voxel_size")} form={form({ voxel_size: 8 })} onChange={() => {}} />);
  expect(slider().value).toBe("5");
  expect(slider().getAttribute("aria-valuetext")).toBe("8 m");
  expect(numberField().value).toBe("8");
});

test("a slider step passes on a clean number, without the noise of floating point", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={viewOf("settings", "voxel_size")} form={form()} onChange={onChange} />);
  setValue(slider(), "0.30000000000000004");
  expect(onChange).toHaveBeenLastCalledWith({ voxel_size: 0.3 });
});

test("a share stored as 0 to 1 slides in percent and is stored as a share", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={viewOf("envelope_and_massing", "plate_tolerance")} form={form()} onChange={onChange} />);
  expect([slider().min, slider().max, slider().step, slider().value]).toEqual(["0", "100", "1", "20"]);
  setValue(slider(), "35");
  expect(onChange).toHaveBeenLastCalledWith({ plate_tolerance: 0.35 });
});

test("an empty automatic setting starts its hollow handle at the value the engine uses, and stays empty until the slider moves", () => {
  const onChange = vi.fn();
  // The engine's descriptions name the automatic values (pydantic_schemas.py): 1.1 x voxel size; 75 ° in the weighted modes.
  const described = initialFormState({ schema: { properties: { ...SCHEMA.properties,
    score_smoothing: { ...SCHEMA.properties.score_smoothing, description: "None (default) = auto: 1.1 × voxel_size, recommended for most runs." },
    max_slope_deg: { anyOf: [{ type: "number", exclusiveMinimum: 0, maximum: 90 }, { type: "null" }], default: null,
                     description: "None (default): 75 for the weighted modes (irradiance, benefit, daylight, radiative_cooling), off for time-based and tilted_plane. 90: off." } } },
    modes: MODES, settings: { mode: "daylight", voxel_size: 2 }, gridPlan: null });
  rendered = renderForTest(<SettingField view={viewOf("carving", "score_smoothing")} form={described} onChange={onChange} />);
  expect(slider().dataset.empty).toBe("true");
  expect(slider().value).toBe("2.2");
  expect(slider().getAttribute("aria-valuetext")).toBe("automatic, 2.2 m");
  expect(numberField().placeholder).toBe("automatic");
  expect(onChange).not.toHaveBeenCalled();
  setValue(slider(), "2.3");
  expect(onChange).toHaveBeenLastCalledWith({ score_smoothing: 2.3 });
  rendered.rerender(<SettingField view={viewOf("carving", "max_slope_deg")} form={described} onChange={onChange} />);
  expect(slider().value).toBe("75");
  expect(slider().getAttribute("aria-valuetext")).toBe("automatic, 75 °");
  // In a mode where an empty slope limit is off, the handle sits at 90, the value that is off, and says so.
  const timeBased = { ...described, scoreKindByMode: { daylight: "violation_count" } };
  rendered.rerender(<SettingField view={viewOf("carving", "max_slope_deg")} form={timeBased} onChange={onChange} />);
  expect(slider().value).toBe("90");
  expect(slider().getAttribute("aria-valuetext")).toBe("automatic, off");
  // Without the engine's number the handle waits in the middle, and the value stays empty.
  rendered.rerender(<SettingField view={viewOf("carving", "score_smoothing")} form={form()} onChange={onChange} />);
  expect(slider().value).toBe("2.5");
  expect(slider().getAttribute("aria-valuetext")).toBe("automatic");
  rendered.rerender(<SettingField view={viewOf("carving", "score_smoothing")} form={form({ score_smoothing: 1.2 })} onChange={onChange} />);
  expect(slider().dataset.empty).toBeUndefined();
});

test("the slider is disabled with its number field, and marked invalid with it after a refused save", () => {
  rendered = renderForTest(<SettingField view={viewOf("settings", "voxel_size")} form={form()} onChange={() => {}} disabled />);
  expect(slider().disabled).toBe(true);
  expect(numberField().disabled).toBe(true);
  const refused = formReducer(form(), { type: "save_rejected", reply: { field_errors: [{ field: "voxel_size", message: "Input should be less than or equal to 100" }], grid_plan: null } });
  rendered.rerender(<SettingField view={viewOf("settings", "voxel_size")} form={refused} onChange={() => {}} />);
  const error = rendered.container.querySelector(".setting-error")!;
  expect(slider().getAttribute("aria-invalid")).toBe("true");
  expect(slider().getAttribute("aria-describedby")).toBe(error.id);
});

test("counts and switches keep their controls: no slider", () => {
  const sliders = (step: Parameters<typeof settingsForStep>[0], name: string) => {
    rendered?.unmount();
    rendered = renderForTest(<SettingField view={viewOf(step, name)} form={form()} onChange={() => {}} />);
    return rendered.container.querySelectorAll("input[type='range']").length;
  };
  expect(sliders("envelope_and_massing", "smooth_iters")).toBe(0);
  expect(sliders("carving", "carve_above_min_consecutive")).toBe(0);
  expect(sliders("settings", "ray_batch_size")).toBe(0);
  expect(sliders("settings", "diagnostics")).toBe(0);
});

test("the computer's settings sit at the end of More detail settings, and the statistics say they change only the report", () => {
  const detail = settingsForStep("settings", "daylight").find((group) => group.title === "Detail")!;
  rendered = renderForTest(<SettingGroup group={detail} form={form()} onChange={() => {}} />);
  act(() => rendered!.container.querySelector<HTMLButtonElement>("button.setting-fold")!.click());
  const labels = [...rendered.container.querySelectorAll(".setting-group-folded .setting-label")].map((label) => label.textContent);
  expect(labels.slice(-2)).toEqual(["Rays per batch", "Detailed statistics"]);
  expect(viewOf("settings", "diagnostics").help).toContain("only the run report");
});
