import { act, createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, type ConfigReply, type ModeInfo } from "../api_client/client";
import { renderForTest } from "../viewer_overlays/render_for_test";
import { createConfigSaver, defaultValue, formReducer, initialFormState, shownValue, useSettingsForm, valuesToSend, type FormAction } from "./form_state";

const SCHEMA = {
  properties: {
    mode: { default: "time-based" }, voxel_size: { default: 1.0 }, north_deg: { default: 0.0 }, carve_fraction: { default: 0.7 },
    start_month: { default: null }, start_day: { default: null }, start_hour: { default: null },
    end_month: { default: null }, end_day: { default: null }, end_hour: { default: null },
    sun_steps_per_hour: { default: 12 }, balance_temperature: { default: 15.0 }, threshold: { default: null },
    score_smoothing: { default: null }, edge_taper: { default: 0.0 },
  },
};

function modeInfo(name: string, startingValues: Record<string, unknown>): ModeInfo {
  return { name, description: "", needs_epw: false, needs_period: false, experimental: false, score_kind: "weighted_sum",
           weight_unit: "", starting_values: startingValues };
}

const period = (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number) => ({
  start_month: startMonth, start_day: startDay, start_hour: startHour, end_month: endMonth, end_day: endDay, end_hour: endHour,
});

const MODES = [modeInfo("time-based", period(12, 21, 10, 12, 21, 14)), modeInfo("irradiance", period(1, 1, 0, 12, 31, 23)),
               modeInfo("benefit", period(10, 15, 7, 4, 15, 19)), modeInfo("daylight", {}),
               modeInfo("radiative_cooling", { carve_fraction: 0.35 }), modeInfo("tilted_plane", { tilted_plane_angle_deg: 45.0 })];

const GRID_PLAN = { resolution: 62, voxel_size: 1, total_voxels: 238328, extent: 62, budget_voxels: 500000000 };

function storedProjectState(settings: Record<string, unknown>) {
  return initialFormState({ schema: SCHEMA, modes: MODES, settings, gridPlan: null });
}

afterEach(() => {
  vi.useRealTimers();
});

test("a stored config is read as the mode's starting values and the settings the user set", () => {
  const state = storedProjectState({ mode: "time-based", ...period(12, 21, 10, 12, 21, 14), voxel_size: 2.0 });
  expect(state.userValues).toEqual({ voxel_size: 2.0 });
  expect(shownValue(state, "voxel_size")).toBe(2.0);
  expect(shownValue(state, "start_hour")).toBe(10);           // the mode's starting value
  expect(shownValue(state, "north_deg")).toBe(0.0);           // the schema default
  expect(defaultValue(state, "voxel_size")).toBe(1.0);
  expect(defaultValue(state, "end_hour")).toBe(14);
  expect(valuesToSend(state)).toEqual({ mode: "time-based", voxel_size: 2.0 });
});

test("choosing a mode fills its starting values and keeps the shared ones the user set", () => {
  let state = storedProjectState({ mode: "time-based", ...period(12, 21, 10, 12, 21, 14) });
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 0.5, north_deg: 20, sun_steps_per_hour: 6, start_hour: 9, threshold: { method: "cutoff", value: 2 } } });
  state = formReducer(state, { type: "mode_chosen", mode: "irradiance" });
  expect(state.mode).toBe("irradiance");
  expect(shownValue(state, "start_month")).toBe(1);
  expect(shownValue(state, "start_hour")).toBe(0);            // the new mode's period replaces the one the user set
  expect(shownValue(state, "voxel_size")).toBe(0.5);
  // The time-based sun sampling is not read by irradiance, and a threshold belongs to the scores of its mode: both are dropped.
  expect(valuesToSend(state)).toEqual({ mode: "irradiance", voxel_size: 0.5, north_deg: 20 });
  state = formReducer(state, { type: "mode_chosen", mode: "radiative_cooling" });
  expect(shownValue(state, "carve_fraction")).toBe(0.35);
  expect(shownValue(state, "start_month")).toBeNull();
  expect(valuesToSend(state)).toEqual({ mode: "radiative_cooling", voxel_size: 0.5, north_deg: 20 });
});

test("a change of a setting the user set back to empty unsets it", () => {
  let state = storedProjectState({ mode: "daylight" });
  state = formReducer(state, { type: "values_changed", values: { score_smoothing: 1.5 } });
  expect(valuesToSend(state)).toEqual({ mode: "daylight", score_smoothing: 1.5 });
  state = formReducer(state, { type: "values_changed", values: { score_smoothing: null } });
  expect(valuesToSend(state)).toEqual({ mode: "daylight" });
});

test("each change marks the form as waiting for a save, and a save reply brings the grid plan", () => {
  let state = storedProjectState({ mode: "daylight" });
  expect(state.pendingSave).toBe(false);
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 1.0 } });
  expect(state.pendingSave).toBe(true);
  expect(state.changeCount).toBe(1);
  state = formReducer(state, { type: "save_succeeded", reply: { settings: { mode: "daylight", voxel_size: 1.0 }, grid_plan: GRID_PLAN } });
  expect(state.pendingSave).toBe(false);
  expect(state.gridPlan).toEqual(GRID_PLAN);
});

test("a 422 puts each field error under its field and a cross-field error on the step", () => {
  let state = storedProjectState({ mode: "daylight" });
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 0.001 } });
  state = formReducer(state, {
    type: "save_rejected",
    reply: { field_errors: [{ field: "voxel_size", message: "Input should be greater than or equal to 0.01" },
                            { field: null, message: "grid_step must not exceed voxel_size" }], grid_plan: null },
  });
  expect(state.fieldErrors).toEqual({ voxel_size: "Input should be greater than or equal to 0.01" });
  expect(state.stepErrors).toEqual(["grid_step must not exceed voxel_size"]);
  expect(state.pendingSave).toBe(false);
  state = formReducer(state, { type: "save_succeeded", reply: { settings: {}, grid_plan: null } });
  expect(state.fieldErrors).toEqual({});
  expect(state.stepErrors).toEqual([]);
});

test("the saver sends 400 ms after the last change, only the latest values, and reads a 422 as field errors", async () => {
  vi.useFakeTimers();
  const actions: FormAction[] = [];
  const reply: ConfigReply = { settings: { mode: "daylight", voxel_size: 3 }, grid_plan: null };
  const save = vi.fn().mockResolvedValueOnce(reply)
    .mockRejectedValueOnce(new ApiError(422, { field_errors: [{ field: "voxel_size", message: "too small" }], grid_plan: null }));
  const saver = createConfigSaver(save, (action) => actions.push(action));
  saver.schedule({ mode: "daylight", voxel_size: 2 });
  await vi.advanceTimersByTimeAsync(300);
  saver.schedule({ mode: "daylight", voxel_size: 3 });
  await vi.advanceTimersByTimeAsync(399);
  expect(save).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(save).toHaveBeenCalledExactlyOnceWith({ mode: "daylight", voxel_size: 3 });
  expect(actions).toEqual([{ type: "save_succeeded", reply }]);
  saver.schedule({ mode: "daylight", voxel_size: 0 });
  await vi.advanceTimersByTimeAsync(400);
  expect(actions[1]).toEqual({ type: "save_rejected", reply: { field_errors: [{ field: "voxel_size", message: "too small" }], grid_plan: null } });
});

test("the saver drops a reply when a newer change has come since its request", async () => {
  vi.useFakeTimers();
  const actions: FormAction[] = [];
  let answerFirstRequest: (reply: ConfigReply) => void = () => {};
  const save = vi.fn()
    .mockImplementationOnce(() => new Promise<ConfigReply>((resolve) => { answerFirstRequest = resolve; }))
    .mockResolvedValueOnce({ settings: { voxel_size: 5 }, grid_plan: null });
  const saver = createConfigSaver(save, (action) => actions.push(action));
  saver.schedule({ voxel_size: 4 });
  await vi.advanceTimersByTimeAsync(400);
  saver.schedule({ voxel_size: 5 });
  answerFirstRequest({ settings: { voxel_size: 4 }, grid_plan: null });
  await vi.advanceTimersByTimeAsync(400);
  expect(actions).toEqual([{ type: "save_succeeded", reply: { settings: { voxel_size: 5 }, grid_plan: null } }]);
});

test("a save that fails for another reason is kept for the caller to show", async () => {
  vi.useFakeTimers();
  const actions: FormAction[] = [];
  const conflict = new ApiError(409, { detail: "A run of this project is in progress." });
  const saver = createConfigSaver(vi.fn().mockRejectedValue(conflict), (action) => actions.push(action));
  saver.schedule({ voxel_size: 4 });
  await vi.advanceTimersByTimeAsync(400);
  expect(actions).toEqual([{ type: "save_failed", error: conflict }]);
  const state = formReducer(storedProjectState({ mode: "daylight" }), actions[0]);
  expect(state.saveFailure).toBe(conflict);
});

test("the form of a project saves each change with PUT config 400 ms later", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ settings: { mode: "daylight", voxel_size: 2 }, grid_plan: GRID_PLAN })));
  vi.stubGlobal("fetch", fetchMock);
  let latest: ReturnType<typeof useSettingsForm> | null = null;
  function FormProbe() {
    latest = useSettingsForm("launch token", "my project", { schema: SCHEMA, modes: MODES, settings: { mode: "daylight" }, gridPlan: null });
    return null;
  }
  const rendered = renderForTest(createElement(FormProbe));
  act(() => latest!.dispatch({ type: "values_changed", values: { voxel_size: 2 } }));
  await act(() => vi.advanceTimersByTimeAsync(399));
  expect(fetchMock).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(fetchMock).toHaveBeenCalledOnce();
  const [address, request] = fetchMock.mock.calls[0];
  expect(address).toBe("/api/projects/my%20project/config");
  expect(JSON.parse(request.body)).toEqual({ values: { voxel_size: 2, mode: "daylight" } });
  expect(latest!.form.gridPlan).toEqual(GRID_PLAN);
  expect(latest!.form.pendingSave).toBe(false);
  rendered.unmount();
  vi.unstubAllGlobals();
});
