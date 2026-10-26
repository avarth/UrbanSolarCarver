import { expect, test } from "vitest";
import { initialFormState, type FormState } from "../settings_form/form_state";
import { CRITERION_KEYS, MODES, SCHEMA } from "../steps/project_workspace_for_test";
import { settingsToFixByStep } from "../steps/SettingsStep";
import {
  carvingRuleSummary, criterionSettingsSummary, DEFAULT_OPEN_SECTIONS, modeSummary, sectionOfSetting, settingsToFixBySection, testSurfacesSummary,
} from "./section_summaries";

function formFor(settings: Record<string, unknown>): FormState {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings, gridPlan: null });
}

test("the test surfaces in one line: the file's name, two names, a count, or none yet", () => {
  expect(testSurfacesSummary([])).toBe("None yet");
  expect(testSurfacesSummary(["windows.ply"])).toBe("windows.ply");
  expect(testSurfacesSummary(["a.ply", "b.ply"])).toBe("a.ply, b.ply");
  expect(testSurfacesSummary(["a.ply", "b.ply", "c.ply"])).toBe("3 files");
});

test("the mode in one line is its plain name", () => {
  expect(modeSummary("daylight")).toBe("Daylight");
  expect(modeSummary("time-based")).toBe("Solar time-based");
});

test("the settings in one line: the analysis period of a mode that reads one", () => {
  expect(criterionSettingsSummary(formFor({ mode: "time-based" }), CRITERION_KEYS)).toBe("21 Dec, 10 to 14 h");
  expect(criterionSettingsSummary(formFor({ mode: "time-based", start_hour: 7, end_hour: 19 }), CRITERION_KEYS)).toBe("21 Dec, 7 to 19 h");
});

test("the settings in one line of a mode without a period: its starting values, or how many of the criterion's settings changed", () => {
  expect(criterionSettingsSummary(formFor({ mode: "daylight" }), CRITERION_KEYS)).toBe("Starting values");
  // A shared setting is Site and grid's: it changes nothing here.
  expect(criterionSettingsSummary(formFor({ mode: "daylight", voxel_size: 2 }), CRITERION_KEYS)).toBe("Starting values");
  // A carving setting is the carving rule's.
  expect(criterionSettingsSummary(formFor({ mode: "daylight", max_slope_deg: 45 }), CRITERION_KEYS)).toBe("Starting values");
  expect(criterionSettingsSummary(formFor({ mode: "daylight", rays_per_patch: 4 }), CRITERION_KEYS)).toBe("1 setting changed");
  expect(criterionSettingsSummary(formFor({ mode: "radiative_cooling", dew_point_celsius: 12, bliss_k: 0.2 }), CRITERION_KEYS)).toBe("2 settings changed");
});

test("the carving rule in one line: the carve amount, a fixed cutoff, Automatic, or the angle rule", () => {
  expect(carvingRuleSummary(formFor({ mode: "daylight", carve_fraction: 0.7 }))).toBe("Carve 70 %");
  expect(carvingRuleSummary(formFor({ mode: "daylight", carve_fraction: 0.705 }))).toBe("Carve 70.5 %");
  expect(carvingRuleSummary(formFor({ mode: "daylight", threshold: { method: "headtail" } }))).toBe("Automatic");
  expect(carvingRuleSummary(formFor({ mode: "daylight", threshold: { method: "cutoff", value: 0.42 } }))).toBe("Cutoff 0.42");
  expect(carvingRuleSummary(formFor({ mode: "daylight", threshold: { method: "cutoff", value: 0.42 } }), "lx")).toBe("Cutoff 0.42 lx");       // the mode's score unit
  expect(carvingRuleSummary(formFor({ mode: "time-based", threshold: { method: "cutoff", value: 1.5 } }))).toBe("Cutoff 1.5 m²·h");
  expect(carvingRuleSummary(formFor({ mode: "time-based" }))).toBe("Cutoff 0 m²·h");       // unset: the engine cuts at 0
  expect(carvingRuleSummary(formFor({ mode: "tilted_plane" }))).toBe("Everything above the planes");
});

test("the section that holds a setting: Mode for the mode, Carving rule for a carving setting, Settings for the others", () => {
  expect(sectionOfSetting("mode")).toBe("mode");
  expect(sectionOfSetting("max_slope_deg")).toBe("carving");
  expect(sectionOfSetting("threshold.value")).toBe("carving");
  expect(sectionOfSetting("start_month")).toBe("settings");
  expect(sectionOfSetting("end_hour")).toBe("settings");
  expect(sectionOfSetting("rays_per_patch")).toBe("settings");
  expect([...DEFAULT_OPEN_SECTIONS].sort()).toEqual(["carving", "test_surfaces"]);
});

test("the settings to fix by section: the criterion's fields with an error, one field for the six period settings, and the messages that name none", () => {
  const form = { ...formFor({ mode: "time-based" }),
    fieldErrors: { start_month: "bad", end_hour: "bad", max_slope_deg: "too steep", mode: "unknown", voxel_size: "too small" },
    stepErrors: ["Add a weather file to run this mode"] };
  expect(settingsToFixBySection(form, CRITERION_KEYS)).toEqual({ settings: 2, carving: 1, mode: 1 });
  expect(settingsToFixBySection(formFor({ mode: "daylight" }), CRITERION_KEYS)).toEqual({});
  // Counted as the steps count them: the mode in Criteria, the shared voxel size in Site and grid.
  expect(settingsToFixByStep({ fieldErrors: {}, stepErrors: [] }, form, CRITERION_KEYS)).toEqual({ criteria: 4, site_and_grid: 1 });
});
