import { expect, test } from "vitest";
import {
  fieldSettingOf, fromDisplayValue, presentedSettingOf, settingIsReadBy, settingsForStep, settingsOfField, settingView, shownSliderOf, toDisplayValue,
} from "./presentation";

const names = (views: { name: string }[]) => views.map((view) => view.name);

test("essential settings of the Settings step per mode", () => {
  const essentialNames = (mode: string) => settingsForStep("settings", mode).flatMap((group) => names(group.essential));
  expect(essentialNames("time-based")).toEqual(["start_month", "north_deg", "voxel_size"]);
  expect(essentialNames("benefit")).toContain("balance_temperature");
  expect(essentialNames("tilted_plane")).toEqual(["north_deg", "tilted_plane_angle_deg", "voxel_size"]);
  expect(essentialNames("radiative_cooling")).toEqual(["north_deg", "dew_point_celsius", "voxel_size"]);
});

test("the Settings step groups, their folds and their fold labels", () => {
  const groups = settingsForStep("settings", "time-based");
  expect(groups.map((group) => group.title)).toEqual(["When", "Detail"]);     // no mode specific settings: left out
  const [when, detail] = groups;
  expect(names(when.folded)).toEqual(["sun_steps_per_hour", "min_altitude"]);
  expect(when.foldLabel).toBe("More sun settings");
  // R2 4.5: the computer's settings come last in the detail fold; the edge strip is for weighted modes.
  expect(names(detail.folded)).toEqual(["grid_step", "ray_length", "margin_frac", "ray_batch_size", "diagnostics"]);
  expect(detail.foldLabel).toBe("More detail settings");
  const benefitModeGroup = settingsForStep("settings", "benefit")[1];
  expect(benefitModeGroup.title).toBe("Mode specific");
  expect(names(benefitModeGroup.essential)).toEqual(["balance_temperature"]);      // with its dead band, as one widget
  expect(names(benefitModeGroup.folded)).toEqual(["include_harm"]);
  expect(benefitModeGroup.foldLabel).toBe("More mode settings");
  const irradianceDetail = settingsForStep("settings", "irradiance").find((group) => group.title === "Detail")!;
  expect(names(irradianceDetail.folded)).toEqual(["grid_step", "edge_taper", "ray_length", "margin_frac", "ray_batch_size", "diagnostics"]);
});

test("settings drawn as one field are found by the name of their first setting", () => {
  expect(fieldSettingOf("end_hour")).toBe("start_month");
  expect(fieldSettingOf("balance_offset")).toBe("balance_temperature");
  expect(fieldSettingOf("voxel_size")).toBe("voxel_size");
  expect(settingsOfField("balance_temperature")).toEqual(["balance_temperature", "balance_offset"]);
  expect(settingsOfField("start_month")).toHaveLength(6);
  expect(settingsOfField("voxel_size")).toEqual(["voxel_size"]);
});

test("a ranged setting has its slider in the units shown: a share stored as 0 to 1 slides from 0 to 100 %", () => {
  expect(shownSliderOf(settingView("voxel_size", "daylight"))).toEqual({ low: 0.1, high: 5, step: 0.1 });
  expect(shownSliderOf(settingView("plate_tolerance", "daylight"))).toEqual({ low: 0, high: 100, step: 1 });
  expect(shownSliderOf(settingView("smooth_iters", "daylight"))).toBeUndefined();      // a count keeps its number field
});

test("the analysis period is one setting labelled by its start month entry", () => {
  const [when] = settingsForStep("settings", "irradiance");
  expect(when.essential[0]).toMatchObject({ name: "start_month", label: "Analysis period", widget: "analysis_period" });
  expect(names(settingsForStep("settings", "daylight")[0].essential)).toEqual(["north_deg"]);
});

test("time-based carving folds the cut-above and slope settings", () => {
  const [group] = settingsForStep("carving", "time-based");
  expect(names(group.essential)).toEqual(["threshold"]);
  expect(group.essential[0]).toMatchObject({ label: "Shadow tolerated", unit: "m²·h" });
  expect(names(group.folded)).toEqual(["carve_above", "carve_above_min_consecutive", "max_slope_deg"]);
  expect(group.foldLabel).toBe("More carving settings");
});

test("weighted carving shows the carve amount and folds the carving rule", () => {
  const [group] = settingsForStep("carving", "daylight");
  expect(names(group.essential)).toEqual(["carve_fraction"]);
  expect(group.essential[0]).toMatchObject({ unit: "%", display: "percent" });
  expect(names(group.folded)).toEqual(["threshold", "score_smoothing", "carve_above", "carve_above_min_consecutive", "max_slope_deg"]);
  expect(group.folded[0]).toMatchObject({ label: "Carving rule", unit: "choice" });
  expect(names(settingsForStep("carving", "tilted_plane")[0].essential)).toEqual([]);
});

test("the envelope and massing step and the export step", () => {
  const [envelope, massing] = settingsForStep("envelope_and_massing", "irradiance");
  expect(names(envelope.essential)).toEqual(["apply_smoothing"]);
  expect(envelope.foldLabel).toBe("More envelope settings");
  expect(names(massing.essential)).toEqual(["ground_floor_height", "floor_height", "min_plate_dimension"]);
  expect(names(massing.folded)).toEqual(["plate_tolerance", "plate_stacking"]);
  expect(massing.foldLabel).toBe("More massing settings");
  const [exportGroup] = settingsForStep("export", "irradiance");
  expect(names(exportGroup.essential)).toEqual(["final_mesh_format"]);
  expect(exportGroup.folded).toEqual([]);
});

test("percent settings convert both ways", () => {
  expect(toDisplayValue("carve_fraction", 0.3)).toBe(30);
  expect(fromDisplayValue("plate_tolerance", 20)).toBe(0.2);
  expect(toDisplayValue("voxel_size", 0.3)).toBe(0.3);
  expect(fromDisplayValue("carve_fraction", null)).toBeNull();
});

test("which modes read a setting", () => {
  expect(settingIsReadBy("voxel_size", "daylight")).toBe(true);
  expect(settingIsReadBy("start_day", "daylight")).toBe(false);
  expect(settingIsReadBy("carve_fraction", "time-based")).toBe(false);
  expect(settingIsReadBy("threshold", "tilted_plane")).toBe(false);
});

test("a field the engine names finds its setting by the name or the part before a dot, never by a name every object has", () => {
  expect(presentedSettingOf("voxel_size")).toBe("voxel_size");
  expect(presentedSettingOf("threshold.value")).toBe("threshold");
  expect(presentedSettingOf("mode")).toBeNull();
  expect(presentedSettingOf("constructor")).toBeNull();
  expect(presentedSettingOf("toString.value")).toBeNull();
});
