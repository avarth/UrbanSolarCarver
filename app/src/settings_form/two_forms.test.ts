import { expect, test } from "vitest";
import { ApiError, type ModeInfo } from "../api_client/client";
import { analysisDiffersFromStored, formReducer, initialFormState, shownValue, valuesToSend, type FormAction, type SettingsForm } from "./form_state";
import { bothForms, combinedForm, combinedSaveOutcome, sharedChangeHeldBack, splitSettings } from "./two_forms";

const SCHEMA = {
  properties: {
    mode: { default: "time-based" }, voxel_size: { default: 1.0 }, north_deg: { default: 0.0 }, carve_fraction: { default: 0.7 },
    start_month: { default: null }, start_day: { default: null }, start_hour: { default: null },
    end_month: { default: null }, end_day: { default: null }, end_hour: { default: null }, threshold: { default: null }, edge_taper: { default: 0.0 },
  },
};

function modeInfo(name: string, startingValues: Record<string, unknown>): ModeInfo {
  return { name, description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: "weighted_sum",
           weight_unit: "", score_unit: "", starting_values: startingValues };
}

const period = (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number) => ({
  start_month: startMonth, start_day: startDay, start_hour: startHour, end_month: endMonth, end_day: endDay, end_hour: endHour,
});

const MODES = [modeInfo("time-based", period(12, 21, 10, 12, 21, 14)), modeInfo("daylight", {})];
const GRID_PLAN = { resolution: 62, voxel_size: 1, total_voxels: 238328, extent: 62, budget_voxels: 500000000 };

// The shared settings and those of one criterion are two forms (ProjectWorkspace): the shared one saves with PUT shared-settings,
// the criterion's with PATCH criteria/{id}, and the steps show both as one until they are split on screen.
const CRITERION_KEYS: ReadonlySet<string> = new Set(["mode", ...Object.keys(period(1, 1, 0, 1, 1, 0)), "threshold", "carve_fraction", "edge_taper"]);

test("settings split into the shared ones and the criterion's by the criterion keys, the mode among the criterion's", () => {
  expect(splitSettings({ mode: "daylight", voxel_size: 2, north_deg: 10, threshold: { method: "headtail" } }, CRITERION_KEYS))
    .toEqual({ shared: { voxel_size: 2, north_deg: 10 }, criterion: { mode: "daylight", threshold: { method: "headtail" } } });
});



test("the form the steps show: each setting from the form that owns it, the shared form's grid, either form's change, error or failure", () => {
  let shared = initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "time-based", voxel_size: 2 }, gridPlan: GRID_PLAN, savesMode: false });
  let criterion = initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "time-based", ...period(3, 21, 10, 12, 21, 14) }, gridPlan: null });
  let shown = combinedForm(shared, criterion);
  expect(shown.mode).toBe("time-based");
  expect([shownValue(shown, "voxel_size"), shownValue(shown, "start_month"), shownValue(shown, "end_hour")]).toEqual([2, 3, 14]);
  expect(shown.gridPlan).toEqual(GRID_PLAN);
  expect([analysisDiffersFromStored(shown), shown.pendingSave]).toEqual([false, false]);

  criterion = formReducer(criterion, { type: "values_changed", values: { start_month: 4 } });
  shown = combinedForm(shared, criterion);
  expect([analysisDiffersFromStored(shown), shown.pendingSave]).toEqual([true, true]);
  criterion = formReducer(criterion, { type: "save_succeeded", reply: { settings: { mode: "time-based", ...period(4, 21, 10, 12, 21, 14) } } });
  shown = combinedForm(shared, criterion);
  expect([analysisDiffersFromStored(shown), shown.pendingSave, shown.storedAnalysisRevision]).toEqual([false, false, 1]);
  expect(shown.gridPlan).toEqual(GRID_PLAN);

  shared = formReducer(shared, { type: "values_changed", values: { voxel_size: 0.001 } });
  expect(analysisDiffersFromStored(combinedForm(shared, criterion))).toBe(true);
  shared = formReducer(shared, { type: "save_rejected", reply: { field_errors: [{ field: "voxel_size", message: "Input should be greater than 0.01" }], grid_plan: null } });
  shown = combinedForm(shared, criterion);
  expect(shown.fieldErrors).toEqual({ voxel_size: "Input should be greater than 0.01" });
  expect(analysisDiffersFromStored(shown)).toBe(true);           // refused: the service still holds the voxel size before
  const conflict = new ApiError(409, { detail: "A run of this project is in progress." });
  criterion = formReducer(criterion, { type: "values_changed", values: { start_month: 5 } });
  criterion = formReducer(criterion, { type: "save_failed", error: conflict });
  expect(combinedForm(shared, criterion).saveFailure).toBe(conflict);
});

test("of the two forms' saves, the outcome that keeps a run from starting is the one told", () => {
  expect(combinedSaveOutcome(["none", "none"])).toBe("none");
  expect(combinedSaveOutcome(["saved", "none"])).toBe("saved");
  expect(combinedSaveOutcome(["none", "saved"])).toBe("saved");
  expect(combinedSaveOutcome(["saved", "refused"])).toBe("refused");
  expect(combinedSaveOutcome(["refused", "failed"])).toBe("failed");
  expect(combinedSaveOutcome(["overtaken", "saved"])).toBe("overtaken");
});

/** A form hook over the reducer, recording the saves asked of it. */
function fakeFormHook(settings: Record<string, unknown>, savesMode = true) {
  let state = initialFormState({ schema: SCHEMA, modes: MODES, settings, gridPlan: null, savesMode });
  const calls: string[] = [];
  const dispatch = (action: FormAction) => { state = formReducer(state, action); };
  const hook: SettingsForm = {
    get form() { return state; },
    get pendingSave() { return state.pendingSave; },
    dispatch,
    flushSave: async () => { calls.push("flush"); return "none"; },
    changeAndSave: async (values) => {
      dispatch({ type: "values_changed", values });
      calls.push(`save at once ${JSON.stringify(values)}`);
      return "saved";
    },
    cancelSave: () => { calls.push("cancel"); },
    currentForm: () => state,
  };
  return { hook, calls };
}

test("the two forms as one: each change goes to the form of its settings, a mode to the criterion's, which the shared form follows", () => {
  const shared = fakeFormHook({ mode: "time-based", voxel_size: 2 }, false), criterion = fakeFormHook({ mode: "time-based" });
  const forms = bothForms(shared.hook, criterion.hook, CRITERION_KEYS);
  forms.dispatch({ type: "values_changed", values: { voxel_size: 3, start_month: 6 } });
  expect(shared.hook.form.userValues).toEqual({ voxel_size: 3 });
  expect(criterion.hook.form.userValues).toEqual({ start_month: 6 });
  expect([shownValue(forms.currentForm(), "voxel_size"), shownValue(forms.currentForm(), "start_month")]).toEqual([3, 6]);
  forms.dispatch({ type: "mode_chosen", mode: "daylight" });
  expect([criterion.hook.form.mode, shared.hook.form.mode]).toEqual(["daylight", "daylight"]);
  expect(shared.hook.form.changeCount).toBe(1);                // the voxel size: following the mode saves nothing
  expect(valuesToSend(shared.hook.form)).toEqual({ voxel_size: 3 });
  expect(valuesToSend(criterion.hook.form)).toEqual({ mode: "daylight" });
});

test("a run's field errors go to the form of the setting each names, one naming none to the criterion's", () => {
  const shared = fakeFormHook({ mode: "time-based" }, false), criterion = fakeFormHook({ mode: "time-based" });
  const forms = bothForms(shared.hook, criterion.hook, CRITERION_KEYS);
  forms.dispatch({ type: "save_rejected", reply: { grid_plan: null, field_errors: [
    { field: "voxel_size", message: "Input should be greater than 0.01" }, { field: "threshold.value", message: "Cutoff threshold must be >= 0" },
    { field: null, message: "Value error, something the form cannot place" }] } });
  expect(shared.hook.form.fieldErrors).toEqual({ voxel_size: "Input should be greater than 0.01" });
  expect(shared.hook.form.stepErrors).toEqual([]);
  expect(criterion.hook.form.fieldErrors).toEqual({ threshold: "Cutoff threshold must be >= 0" });
  expect(criterion.hook.form.stepErrors).toEqual(["Something the form cannot place"]);
});

test("a change saved at once goes to the form of its settings, the other form's waiting change flushed; the carving's empty one to the criterion's", async () => {
  const shared = fakeFormHook({ mode: "time-based" }, false), criterion = fakeFormHook({ mode: "time-based" });
  const forms = bothForms(shared.hook, criterion.hook, CRITERION_KEYS);
  expect(await forms.changeAndSave({ final_mesh_format: "obj" })).toBe("saved");
  expect([shared.calls, criterion.calls]).toEqual([['save at once {"final_mesh_format":"obj"}'], ["flush"]]);
  expect(await forms.changeAndSave({})).toBe("saved");
  expect([shared.calls.at(-1), criterion.calls.at(-1)]).toEqual(["flush", "save at once {}"]);
  expect(await forms.flushSave()).toBe("none");
  forms.cancelSave();
  expect([shared.calls.slice(-2), criterion.calls.slice(-2)]).toEqual([["flush", "cancel"], ["flush", "cancel"]]);
});

test("the shared form holds back a change while its save waits for nothing: refused, or not the stored values", () => {
  let shared = initialFormState({ schema: SCHEMA, modes: MODES, settings: { mode: "time-based", voxel_size: 2 }, gridPlan: null, savesMode: false });
  expect(sharedChangeHeldBack(shared)).toBe(false);
  shared = formReducer(shared, { type: "values_changed", values: { voxel_size: 3 } });
  expect(sharedChangeHeldBack(shared)).toBe(false);                // its save is on its way
  shared = formReducer(shared, { type: "save_rejected", reply: { field_errors: [{ field: null, message: "Value error, mode 'time-based' requires epw_path" }], grid_plan: null } });
  expect(sharedChangeHeldBack(shared)).toBe(true);
  shared = formReducer(shared, { type: "values_changed", values: {} });
  shared = formReducer(shared, { type: "save_succeeded", reply: { settings: { voxel_size: 3 }, grid_plan: null } });
  expect(sharedChangeHeldBack(shared)).toBe(false);
});
