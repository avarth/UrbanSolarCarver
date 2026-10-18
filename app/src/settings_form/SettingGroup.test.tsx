import { readFileSync } from "node:fs";
import { act } from "react";
import { afterEach, expect, test, vi } from "vitest";
import type { ModeInfo } from "../api_client/client";
import { click, renderForTest, type RenderedOverlay } from "../viewer_overlays/render_for_test";
import { formReducer, initialFormState, type FormState } from "./form_state";
import { settingsForStep } from "./presentation";
import { SettingField } from "./SettingField";
import { SettingGroup } from "./SettingGroup";

const SCHEMA = {
  properties: {
    mode: { default: "time-based", type: "string" },
    voxel_size: { default: 1.0, type: "number" },
    north_deg: { default: 0.0, type: "number" },
    carve_fraction: { default: 0.7, type: "number" },
    threshold: { anyOf: [{ $ref: "#/$defs/ThresholdSpec" }, { type: "null" }], default: null },
    carve_above: { default: true, type: "boolean" },
    carve_above_min_consecutive: { default: 1, type: "integer" },
    max_slope_deg: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
    score_smoothing: { anyOf: [{ type: "number" }, { type: "null" }], default: null },
    ray_batch_size: { default: 0, type: "integer" },
    diagnostics: { default: false, type: "boolean" },
    start_month: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    start_day: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    start_hour: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_month: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_day: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    end_hour: { anyOf: [{ type: "integer" }, { type: "null" }], default: null },
    smooth_iters: { default: 2, minimum: 0, maximum: 6, type: "integer" },
    ground_floor_height: { default: 5.0, type: "number" },
    floor_height: { default: 3.0, type: "number" },
    min_plate_dimension: { default: 3.0, type: "number" },
    plate_tolerance: { default: 0.2, type: "number" },
    plate_stacking: { default: "supported", enum: ["supported", "free"], type: "string" },
    tilted_plane_angle_deg: { anyOf: [{ type: "number" }, { type: "array", items: { type: "number" } }, { type: "null" }], default: null },
  },
};

const MODES: ModeInfo[] = [
  { name: "time-based", description: "", needs_epw: true, needs_period: true, experimental: false, score_kind: "violation_count", weight_unit: "",
    starting_values: { start_month: 12, start_day: 21, start_hour: 10, end_month: 12, end_day: 21, end_hour: 14 } },
  { name: "daylight", description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: "weighted_sum", weight_unit: "",
    starting_values: {} },
  { name: "tilted_plane", description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: "violation_count",
    weight_unit: "", starting_values: { tilted_plane_angle_deg: 45.0 } },
];

const GRID_PLAN = { resolution: 62, voxel_size: 1, total_voxels: 238328, extent: 62, budget_voxels: 500000000 };

let rendered: RenderedOverlay | null = null;

afterEach(() => {
  rendered?.unmount();
  rendered = null;
});

function formFor(mode: string): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode }, gridPlan: GRID_PLAN });
}

function viewOf(step: Parameters<typeof settingsForStep>[0], mode: string, name: string) {
  const views = settingsForStep(step, mode).flatMap((group) => [...group.essential, ...group.folded]);
  return views.find((view) => view.name === name)!;
}

/** Types *text* into a field the way the browser does, so React's change handler runs. */
function typeInto(field: HTMLInputElement | HTMLSelectElement, text: string): void {
  const prototype = field instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  act(() => {
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(field, text);
    field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
}

function pressEscape(target: Element): void {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
}

test("the tooltip opens on hover, focus and click, closes with Escape, and gives the config name, default and grid", () => {
  rendered = renderForTest(<SettingField view={viewOf("settings", "daylight", "voxel_size")} form={formFor("daylight")} onChange={() => {}} />);
  const infoButton = rendered.container.querySelector<HTMLButtonElement>("button.setting-info")!;
  expect(infoButton.getAttribute("aria-expanded")).toBe("false");
  expect(rendered.container.querySelector("[role='tooltip']")).toBeNull();

  act(() => { infoButton.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); });
  const tooltip = rendered.container.querySelector("[role='tooltip']")!;
  expect(tooltip.textContent).toContain("Edge of the cubes the volume is divided into.");
  expect(tooltip.textContent).toContain("Config name: voxel_size, default 1.0\u00a0m");
  expect(tooltip.querySelector("code")!.textContent).toBe("voxel_size");
  expect(tooltip.textContent).toContain("62 voxels per side, 238\u202f328 in total");
  expect(infoButton.getAttribute("aria-expanded")).toBe("true");
  pressEscape(infoButton);
  expect(rendered.container.querySelector("[role='tooltip']")).toBeNull();

  act(() => { infoButton.dispatchEvent(new MouseEvent("mouseout", { bubbles: true })); });
  act(() => infoButton.focus());
  expect(rendered.container.querySelector("[role='tooltip']")).not.toBeNull();
  act(() => infoButton.blur());
  expect(rendered.container.querySelector("[role='tooltip']")).toBeNull();
  click(infoButton);
  expect(rendered.container.querySelector("[role='tooltip']")).not.toBeNull();
  click(infoButton);
  expect(rendered.container.querySelector("[role='tooltip']")).toBeNull();
});

test("a field has its label, its unit, and its value in the unit shown", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={viewOf("carving", "daylight", "carve_fraction")} form={formFor("daylight")} onChange={onChange} />);
  expect(rendered.container.textContent).toContain("Carve amount");
  expect(rendered.container.textContent).toContain("%");
  const numberField = rendered.container.querySelector<HTMLInputElement>("input[type='number']")!;
  expect(numberField.value).toBe("70");
  expect(rendered.container.querySelector<HTMLInputElement>("input[type='range']")!.value).toBe("70");
  typeInto(numberField, "30");
  expect(onChange).toHaveBeenLastCalledWith({ carve_fraction: 0.3 });
});

test("the analysis period is one widget that changes the six period settings", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={viewOf("settings", "time-based", "start_month")} form={formFor("time-based")} onChange={onChange} />);
  expect(rendered.container.textContent).toContain("Analysis period");
  const startDay = rendered.container.querySelector<HTMLInputElement>("input[aria-label='Start day']")!;
  expect(startDay.value).toBe("21");
  typeInto(startDay, "5");
  expect(onChange).toHaveBeenLastCalledWith({ start_day: 5 });
  const endMonth = rendered.container.querySelector<HTMLSelectElement>("select[aria-label='End month']")!;
  expect(endMonth.value).toBe("12");
  typeInto(endMonth, "3");
  expect(onChange).toHaveBeenLastCalledWith({ end_month: 3 });
});

test("the plane angle takes one value or one per compass direction", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={viewOf("settings", "tilted_plane", "tilted_plane_angle_deg")} form={formFor("tilted_plane")} onChange={onChange} />);
  expect(rendered.container.querySelector<HTMLInputElement>("input[type='number']")!.value).toBe("45");
  click(rendered.container.querySelector("input[type='radio'][value='per_direction']")!);
  expect(onChange).toHaveBeenLastCalledWith({ tilted_plane_angle_deg: [45, 45, 45, 45, 45, 45, 45, 45] });
});

test("the shadow tolerated number sets a cutoff, and the weighted modes choose a carving rule", () => {
  const onChange = vi.fn();
  rendered = renderForTest(<SettingField view={viewOf("carving", "time-based", "threshold")} form={formFor("time-based")} onChange={onChange} />);
  expect(rendered.container.textContent).toContain("Shadow tolerated");
  typeInto(rendered.container.querySelector<HTMLInputElement>("input[type='number']")!, "5");
  expect(onChange).toHaveBeenLastCalledWith({ threshold: { method: "cutoff", value: 5 } });
  rendered.unmount();
  rendered = renderForTest(<SettingField view={viewOf("carving", "daylight", "threshold")} form={formFor("daylight")} onChange={onChange} />);
  expect(rendered.container.textContent).toContain("Carving rule");
  const rule = rendered.container.querySelector<HTMLSelectElement>("select")!;
  expect(rule.value).toBe("carve_fraction");
  typeInto(rule, "headtail");
  expect(onChange).toHaveBeenLastCalledWith({ threshold: { method: "headtail" } });
  typeInto(rule, "carve_fraction");
  expect(onChange).toHaveBeenLastCalledWith({ threshold: null });
});

test("a group folds its other settings under a link-styled button named after the group", () => {
  const [group] = settingsForStep("carving", "time-based");
  rendered = renderForTest(<SettingGroup group={group} form={formFor("time-based")} onChange={() => {}} />);
  expect(rendered.container.querySelector(".setting-group-title")!.textContent).toBe("How much to carve");
  const foldButton = rendered.container.querySelector<HTMLButtonElement>("button.setting-fold")!;
  expect(foldButton.textContent).toBe("More carving settings");
  expect(foldButton.getAttribute("aria-expanded")).toBe("false");
  expect(rendered.container.textContent).not.toContain("Remove everything above a cut");
  click(foldButton);
  expect(foldButton.getAttribute("aria-expanded")).toBe("true");
  expect(rendered.container.textContent).toContain("Remove everything above a cut");
});

test("a group without essential settings is one fold titled with the group name", () => {
  const computer = settingsForStep("settings", "daylight").find((group) => group.title === "Computer")!;
  rendered = renderForTest(<SettingGroup group={computer} form={formFor("daylight")} onChange={() => {}} />);
  expect(rendered.container.querySelector(".setting-group-title")).toBeNull();
  expect(rendered.container.querySelector("button.setting-fold")!.textContent).toBe("Computer");
});

test("the building massing essentials sit side by side", () => {
  const [, massing] = settingsForStep("envelope_and_massing", "daylight");
  rendered = renderForTest(<SettingGroup group={massing} form={formFor("daylight")} onChange={() => {}} />);
  expect(rendered.container.querySelector(".setting-group-essential")!.classList).toContain("setting-group-side-by-side");
});

test("a field error is shown under its field, and opens the fold that holds it", () => {
  let form = formFor("time-based");
  form = formReducer(form, { type: "save_rejected", reply: { field_errors: [{ field: "max_slope_deg", message: "Input should be less than or equal to 90" }], grid_plan: null } });
  const [group] = settingsForStep("carving", "time-based");
  rendered = renderForTest(<SettingGroup group={group} form={form} onChange={() => {}} />);
  const error = rendered.container.querySelector(".setting-error")!;
  expect(error.textContent).toContain("Input should be less than or equal to 90");
  const invalidFields = rendered.container.querySelectorAll<HTMLInputElement>("input[aria-invalid='true']");
  expect(invalidFields).toHaveLength(1);
  expect(invalidFields[0].getAttribute("aria-describedby")).toContain(error.id);
  expect(rendered.container.querySelector("button.setting-fold")!.getAttribute("aria-expanded")).toBe("true");
});

test("an optional number left empty is sent as unset", () => {
  const onChange = vi.fn();
  let form = formFor("daylight");
  form = formReducer(form, { type: "values_changed", values: { score_smoothing: 1.2 } });
  rendered = renderForTest(<SettingField view={viewOf("carving", "daylight", "score_smoothing")} form={form} onChange={onChange} />);
  const field = rendered.container.querySelector<HTMLInputElement>("input[type='number']")!;
  expect(field.value).toBe("1.2");
  typeInto(field, "");
  expect(onChange).toHaveBeenLastCalledWith({ score_smoothing: null });
});

test("the settings form styles take every colour from the tokens", () => {
  const formCss = readFileSync("src/settings_form/settings_form.css", "utf8");
  expect(formCss).not.toMatch(/#[0-9a-f]{3,6}\b|rgb\(/i);
  expect(formCss).toMatch(/\.setting-info\[aria-expanded="true"\]\s*{[^}]*background: var\(--colour-accent-soft\)/);
  expect(formCss).toMatch(/\.setting-group-title\s*{[^}]*font-size: var\(--text-secondary\);[^}]*font-weight: 600;[^}]*color: var\(--colour-muted\)/);
});

test("an invalid field is marked without the outline, which stays the focus mark", () => {
  const formCss = readFileSync("src/settings_form/settings_form.css", "utf8");
  const invalidRules = formCss.match(/[^}]*\[aria-invalid="true"\][^{]*{[^}]*}/g)!;
  expect(invalidRules.length).toBeGreaterThan(0);
  for (const rule of invalidRules) {
    expect(rule).not.toMatch(/outline(-offset)?\s*:/);
    expect(rule).toMatch(/box-shadow:[^;]*var\(--colour-error\)/);
  }
  expect(formCss).not.toMatch(/outline\s*:/);       // nothing in the form replaces the focus outline of tokens.css
});

test("the tooltip stays open while the pointer moves from the i onto it, over a strip across the gap", () => {
  rendered = renderForTest(<SettingField view={viewOf("settings", "daylight", "voxel_size")} form={formFor("daylight")} onChange={() => {}} />);
  const infoButton = rendered.container.querySelector<HTMLButtonElement>("button.setting-info")!;
  act(() => { infoButton.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); });
  const tooltip = rendered.container.querySelector("[role='tooltip']")!;
  act(() => { infoButton.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: tooltip })); });
  act(() => { tooltip.dispatchEvent(new MouseEvent("mouseover", { bubbles: true, relatedTarget: infoButton })); });
  expect(rendered.container.querySelector("[role='tooltip']")).not.toBeNull();
  act(() => { tooltip.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: document.body })); });
  expect(rendered.container.querySelector("[role='tooltip']")).toBeNull();
  const formCss = readFileSync("src/settings_form/settings_form.css", "utf8");
  expect(formCss).toMatch(/\.setting-tooltip::after\s*{[^}]*top: -9px;[^}]*height: 9px;/);
});

test("a tooltip opened by a click closes when the pointer presses elsewhere", () => {
  rendered = renderForTest(<SettingField view={viewOf("settings", "daylight", "voxel_size")} form={formFor("daylight")} onChange={() => {}} />);
  const infoButton = rendered.container.querySelector<HTMLButtonElement>("button.setting-info")!;
  click(infoButton);
  act(() => { rendered!.container.querySelector("[role='tooltip']")!.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(rendered.container.querySelector("[role='tooltip']")).not.toBeNull();      // a press on the tooltip itself keeps it
  act(() => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
  expect(rendered.container.querySelector("[role='tooltip']")).toBeNull();
});

test("a range given as the unit is shown beside the value but not after the default", () => {
  rendered = renderForTest(<SettingField view={viewOf("envelope_and_massing", "daylight", "smooth_iters")} form={formFor("daylight")} onChange={() => {}} />);
  expect(rendered.container.querySelector(".setting-unit")!.textContent).toBe("0 to 6");
  click(rendered.container.querySelector("button.setting-info")!);
  expect(rendered.container.querySelector("[role='tooltip']")!.textContent).toContain("Config name: smooth_iters, default 2");
  expect(rendered.container.querySelector("[role='tooltip']")!.textContent).not.toContain("default 2 0 to 6");
});

test("a number outside the engine's range is refused in the field, with a message, and never reaches the form", () => {
  const onChange = vi.fn();
  const form = initialFormState({
    schema: { properties: { ...SCHEMA.properties,
      max_slope_deg: { anyOf: [{ type: "number", exclusiveMinimum: 0, maximum: 90 }, { type: "null" }], default: null },
      north_deg: { default: 0.0, type: "number", minimum: 0, exclusiveMaximum: 360 },
      carve_above_min_consecutive: { default: 1, type: "integer", minimum: 1 } } },
    modes: MODES, settings: { mode: "daylight" }, gridPlan: GRID_PLAN });
  const fieldOf = (step: Parameters<typeof settingsForStep>[0], name: string) => {
    rendered?.unmount();
    rendered = renderForTest(<SettingField view={viewOf(step, "daylight", name)} form={form} onChange={onChange} />);
    return rendered.container.querySelector<HTMLInputElement>("input[type='number']")!;
  };
  const message = () => rendered!.container.querySelector(".setting-error")?.textContent ?? null;

  let field = fieldOf("carving", "max_slope_deg");
  expect([field.min, field.max]).toEqual(["0", "90"]);
  typeInto(field, "0");
  expect(onChange).not.toHaveBeenCalled();
  expect(message()).toBe("Use a number above 0, up to 90.");
  expect(field.getAttribute("aria-invalid")).toBe("true");
  expect(field.getAttribute("aria-describedby")).toBe(rendered!.container.querySelector(".setting-error")!.id);
  typeInto(field, "91");
  expect(onChange).not.toHaveBeenCalled();
  typeInto(field, "45");
  expect(onChange).toHaveBeenLastCalledWith({ max_slope_deg: 45 });
  expect(message()).toBeNull();

  field = fieldOf("settings", "north_deg");
  typeInto(field, "360");
  expect(message()).toBe("Use 0 or more, below 360.");
  typeInto(field, "-1");
  expect(message()).toBe("Use 0 or more, below 360.");
  // Leaving the field shows the value the form holds again, and the message says why the typed one was not taken.
  act(() => field.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));
  expect(field.value).toBe("0");
  expect(message()).toBe("Use 0 or more, below 360.");
  typeInto(field, "359.5");
  expect(onChange).toHaveBeenLastCalledWith({ north_deg: 359.5 });
  expect(message()).toBeNull();

  field = fieldOf("carving", "carve_above_min_consecutive");
  typeInto(field, "2.5");
  expect(message()).toBe("Use a whole number.");
  typeInto(field, "0");
  expect(message()).toBe("Use 1 or more.");
  expect(onChange).toHaveBeenCalledTimes(2);
});

test("a setting whose empty value is automatic shows 'automatic' in the empty field and says in its tooltip what empty does in the mode", () => {
  const tooltipOf = (mode: string) => {
    rendered?.unmount();
    rendered = renderForTest(<SettingField view={viewOf("carving", mode, "max_slope_deg")} form={formFor(mode)} onChange={() => {}} />);
    expect(rendered.container.querySelector<HTMLInputElement>("input[type='number']")!.placeholder).toBe("automatic");
    click(rendered.container.querySelector("button.setting-info")!);
    return rendered.container.querySelector("[role='tooltip']")!.textContent;
  };
  expect(tooltipOf("daylight")).toContain("Left empty, it is 75 ° in Daylight.");
  expect(tooltipOf("time-based")).toContain("Left empty, it is off in Sun at set hours.");
  expect(tooltipOf("tilted_plane")).toContain("Left empty, it is off in Angle rule.");
  // A setting with a value of its own shows no placeholder.
  rendered?.unmount();
  rendered = renderForTest(<SettingField view={viewOf("settings", "daylight", "voxel_size")} form={formFor("daylight")} onChange={() => {}} />);
  expect(rendered.container.querySelector<HTMLInputElement>("input[type='number']")!.placeholder).toBe("");
});
