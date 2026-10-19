import { act, createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { ApiError, type ConfigErrorReply, type ConfigReply, type ModeInfo } from "../api_client/client";
import { renderForTest } from "../viewer_overlays/render_for_test";
import {
  analysisDiffersFromStored, createConfigSaver, defaultValue, formReducer, initialFormState, shownValue, useSettingsForm, valuesToSend, type FormAction,
} from "./form_state";

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

test("a 422 puts each field error under its field, and an error of the whole config under the settings it names", () => {
  let state = storedProjectState({ mode: "daylight" });
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 0.001 } });
  state = formReducer(state, {
    type: "save_rejected",
    reply: { field_errors: [{ field: "voxel_size", message: "Input should be greater than or equal to 0.01" },
                            { field: null, message: "ray_length must be longer than voxel_size" }], grid_plan: null },
  });
  expect(state.fieldErrors).toEqual({ voxel_size: "Input should be greater than or equal to 0.01 Ray length must be longer than voxel size",
                                      ray_length: "Ray length must be longer than voxel size" });
  expect(state.stepErrors).toEqual([]);
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

test("an error the engine names after a dot goes under its setting, and one of a setting not in the form goes to the step", () => {
  let state = storedProjectState({ mode: "time-based" });
  state = formReducer(state, {
    type: "save_rejected",
    reply: { field_errors: [{ field: "threshold.value", message: "cutoff threshold must be >= 0" },
                            { field: "tilted_plane_angle_deg.float", message: "Input should be a valid number" },
                            { field: "mode", message: "mode must be one of the six modes" }], grid_plan: null },
  });
  // The plane angle has no field in Solar time-based: its error is said for the step, with its name.
  expect(state.fieldErrors).toEqual({ threshold: "Cutoff threshold must be >= 0" });
  expect(state.stepErrors).toEqual(["Plane angle: Input should be a valid number", "Mode: mode must be one of the six modes"]);
});

test("flushing the saver sends a waiting save at once and resolves once its reply is passed on", async () => {
  vi.useFakeTimers();
  const actions: FormAction[] = [];
  const reply: ConfigReply = { settings: { voxel_size: 2 }, grid_plan: GRID_PLAN };
  const save = vi.fn().mockResolvedValue(reply);
  const saver = createConfigSaver(save, (action) => actions.push(action));
  expect(await saver.flush()).toBe("none");                 // nothing waiting: resolves without a request
  expect(save).not.toHaveBeenCalled();
  saver.schedule({ voxel_size: 2 });
  expect(await saver.flush()).toBe("saved");
  expect(save).toHaveBeenCalledExactlyOnceWith({ voxel_size: 2 });
  expect(actions).toEqual([{ type: "save_succeeded", reply }]);
  await vi.advanceTimersByTimeAsync(400);
  expect(save).toHaveBeenCalledOnce();                       // the timer of the flushed save sends nothing more
});

test("flushing tells a refused or failed save from a stored one, so a run never starts on settings that were not saved", async () => {
  const refusal: ConfigErrorReply = { field_errors: [{ field: "voxel_size", message: "too small" }], grid_plan: null };
  const save = vi.fn()
    .mockRejectedValueOnce(new ApiError(422, refusal))
    .mockRejectedValueOnce(new ApiError(409, { detail: "A run of project 'p' is active." }));
  const saver = createConfigSaver(save, () => {});
  saver.schedule({ voxel_size: 0.001 });
  expect(await saver.flush()).toBe("refused");
  expect(await saver.flush()).toBe("refused");             // nothing new waiting: the last save's outcome
  saver.schedule({ voxel_size: 2 });
  expect(await saver.flush()).toBe("failed");
});

test("a save that failed without field errors is sent again by the next flush, so a run does not stop at the old failure", async () => {
  const actions: FormAction[] = [];
  const conflict = new ApiError(409, { detail: "A run of project 'p' is active." });
  const reply: ConfigReply = { settings: { voxel_size: 2 }, grid_plan: null };
  const save = vi.fn().mockRejectedValueOnce(conflict).mockRejectedValueOnce(conflict).mockResolvedValueOnce(reply);
  const saver = createConfigSaver(save, (action) => actions.push(action));
  saver.schedule({ voxel_size: 2 });
  expect(await saver.flush()).toBe("failed");
  expect(await saver.flush()).toBe("failed");                // sent again, and refused again
  expect(await saver.flush()).toBe("saved");
  expect(save.mock.calls).toEqual([[{ voxel_size: 2 }], [{ voxel_size: 2 }], [{ voxel_size: 2 }]]);
  expect(actions.map((action) => action.type)).toEqual(["save_failed", "save_failed", "save_succeeded"]);
  expect(await saver.flush()).toBe("saved");                 // stored: nothing is sent again
  expect(save).toHaveBeenCalledTimes(3);
});

test("a flush whose save a newer change overtook resolves with the newer change's save, sent at once", async () => {
  vi.useFakeTimers();
  let answerFirstRequest: (reply: ConfigReply) => void = () => {};
  const newerReply: ConfigReply = { settings: { voxel_size: 5 }, grid_plan: null };
  const save = vi.fn()
    .mockImplementationOnce(() => new Promise<ConfigReply>((resolve) => { answerFirstRequest = resolve; }))
    .mockResolvedValueOnce(newerReply);
  const actions: FormAction[] = [];
  const saver = createConfigSaver(save, (action) => actions.push(action));
  saver.schedule({ voxel_size: 4 });
  const flushed = saver.flush();
  saver.schedule({ voxel_size: 5 });                        // waits for its delay
  answerFirstRequest({ settings: { voxel_size: 4 }, grid_plan: null });
  expect(await flushed).toBe("saved");
  expect(save.mock.calls).toEqual([[{ voxel_size: 4 }], [{ voxel_size: 5 }]]);
  expect(actions).toEqual([{ type: "save_succeeded", reply: newerReply }]);
  await vi.advanceTimersByTimeAsync(400);
  expect(save).toHaveBeenCalledTimes(2);                     // the newer change's timer sends nothing more
  save.mockResolvedValueOnce({ settings: { voxel_size: 6 }, grid_plan: null });
  saver.schedule({ voxel_size: 6 });
  const cancelled = saver.flush();
  saver.cancel();
  expect(await cancelled).toBe("overtaken");                 // cancelled on its way, with no newer save to wait for
  expect(save).toHaveBeenCalledTimes(3);
});

function renderedForm(project: string, settings: Record<string, unknown>, schema: Record<string, unknown> = SCHEMA) {
  let latest: ReturnType<typeof useSettingsForm> | null = null;
  function FormProbe({ projectName, projectSettings }: { projectName: string; projectSettings: Record<string, unknown> }) {
    latest = useSettingsForm("launch token", projectName, { schema, modes: MODES, settings: projectSettings, gridPlan: null });
    return null;
  }
  const rendered = renderForTest(createElement(FormProbe, { projectName: project, projectSettings: settings }));
  return {
    current: () => latest!,
    openProject: (name: string, nameSettings: Record<string, unknown>) => rendered.rerender(createElement(FormProbe, { projectName: name, projectSettings: nameSettings })),
    unmount: rendered.unmount,
  };
}

test("opening another project shows its settings and sends it nothing; a change still waiting goes to the project it was made in", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ settings: {}, grid_plan: GRID_PLAN })));
  vi.stubGlobal("fetch", fetchMock);
  const form = renderedForm("first", { mode: "daylight" });
  act(() => form.current().dispatch({ type: "values_changed", values: { voxel_size: 2 } }));
  await act(() => vi.advanceTimersByTimeAsync(100));
  form.openProject("second", { mode: "irradiance", voxel_size: 3 });
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(fetchMock.mock.calls.map(([address]) => address)).toEqual(["/api/projects/first/config"]);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ values: { voxel_size: 2, mode: "daylight" } });
  expect(form.current().form.mode).toBe("irradiance");
  expect(form.current().form.userValues).toEqual({ voxel_size: 3 });
  expect(form.current().form.gridPlan).toBeNull();          // the first project's reply is not shown in the second's form
  expect(form.current().pendingSave).toBe(false);
  act(() => form.current().dispatch({ type: "values_changed", values: { north_deg: 10 } }));
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(fetchMock.mock.calls[1][0]).toBe("/api/projects/second/config");
  form.unmount();
  vi.unstubAllGlobals();
});

test("the form's flushSave sends a change at once, for a run that must use it", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ settings: {}, grid_plan: GRID_PLAN })));
  vi.stubGlobal("fetch", fetchMock);
  const form = renderedForm("first", { mode: "daylight" });
  act(() => form.current().dispatch({ type: "values_changed", values: { voxel_size: 2 } }));
  expect(form.current().pendingSave).toBe(true);
  await act(() => form.current().flushSave());
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(form.current().pendingSave).toBe(false);
  expect(form.current().form.gridPlan).toEqual(GRID_PLAN);
  form.unmount();
  vi.unstubAllGlobals();
});

test("changeAndSave sets values and saves them at once with the changes before them; the delay then sends nothing more", async () => {
  vi.useFakeTimers();
  const fetchMock = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ settings: {}, grid_plan: GRID_PLAN })));
  vi.stubGlobal("fetch", fetchMock);
  const form = renderedForm("first", { mode: "daylight" });
  act(() => form.current().dispatch({ type: "values_changed", values: { voxel_size: 2 } }));
  let outcome: unknown;
  await act(async () => { outcome = await form.current().changeAndSave({ carve_fraction: 0.5 }); });
  expect(outcome).toBe("saved");
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ values: { voxel_size: 2, carve_fraction: 0.5, mode: "daylight" } });
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(form.current().form.userValues).toEqual({ voxel_size: 2, carve_fraction: 0.5 });
  expect(form.current().pendingSave).toBe(false);
  act(() => form.current().dispatch({ type: "values_changed", values: { north_deg: 10 } }));
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(fetchMock).toHaveBeenCalledTimes(2);                // a later change is saved after the delay as before
  form.unmount();
  vi.unstubAllGlobals();
});

const reject = (state: ReturnType<typeof storedProjectState>, fieldErrors: { field: string | null; message: string }[]) =>
  formReducer(state, { type: "save_rejected", reply: { field_errors: fieldErrors, grid_plan: null } });

test("an error of the whole config is put, in the interface's words, under each setting it names; the last grid plan stays", () => {
  let state = storedProjectState({ mode: "time-based" });
  state = formReducer(state, { type: "save_succeeded", reply: { settings: { mode: "time-based" }, grid_plan: GRID_PLAN } });
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 0.5 } });
  state = reject(state, [{ field: null, message: "Value error, ray_length (5 m) must be longer than voxel_size (0.5 m)" }]);
  const tooShort = "Ray length (5 m) must be longer than voxel size (0.5 m)";
  expect(state.fieldErrors).toEqual({ ray_length: tooShort, voxel_size: tooShort });
  expect(state.stepErrors).toEqual([]);
  expect(state.gridPlan).toEqual(GRID_PLAN);

  state = reject(state, [{ field: null, message: "Value error, start_day=31 is invalid for month 2 (max 28 days)" }]);
  expect(state.fieldErrors).toEqual({ start_day: "February has 28 days, so the start day cannot be 31." });
  state = reject(state, [{ field: null, message: "Value error, end_day=30 is invalid for month 2 (max 28 days)" }]);
  expect(state.fieldErrors).toEqual({ end_day: "February has 28 days, so the end day cannot be 30." });
  state = reject(state, [{ field: null, message: "Value error, mode 'time-based' requires analysis period fields: start_day, end_day" }]);
  expect(state.fieldErrors).toEqual({ start_month: "Solar time-based needs the whole analysis period: every day, month and hour." });
  state = reject(state, [{ field: null, message: "Value error, mode 'time-based' requires epw_path" }]);
  expect(state.fieldErrors).toEqual({});
  expect(state.stepErrors).toEqual(["Add a weather file to run this mode"]);
});

test("any other engine message loses the 'Value error' prefix and has the labels in place of the config names", () => {
  let state = storedProjectState({ mode: "tilted_plane" });
  state = reject(state, [{ field: null, message: "Value error, tilted_plane_angle_deg must have length 8 [N, NE, E, SE, S, SW, W, NW]" }]);
  expect(state.fieldErrors).toEqual({ tilted_plane_angle_deg: "Plane angle must have length 8 [N, NE, E, SE, S, SW, W, NW]" });
  state = reject(state, [{ field: "north_deg", message: "Value error, north_deg is out of range" }]);
  expect(state.fieldErrors).toEqual({ north_deg: "North direction is out of range" });
  state = reject(state, [{ field: null, message: "Value error, something the form cannot place" }]);
  expect(state.stepErrors).toEqual(["Something the form cannot place"]);
  expect(state.fieldErrors).toEqual({});
});

test("choosing a mode leaves no error of the mode before: its save brings the new mode's own", () => {
  let state = storedProjectState({ mode: "daylight" });
  state = reject(state, [{ field: "edge_taper", message: "Input should be greater than or equal to 0" },
                         { field: null, message: "Value error, the settings do not fit together" }]);
  state = formReducer(state, { type: "mode_chosen", mode: "time-based" });
  expect(state.fieldErrors).toEqual({});
  expect(state.stepErrors).toEqual([]);
});

test("a value the user set that was refused is not carried to the new mode: it goes back to the default, and the form says so", () => {
  let state = storedProjectState({ mode: "daylight" });
  state = formReducer(state, { type: "values_changed", values: { max_slope_deg: 0, voxel_size: 2 } });
  state = reject(state, [{ field: "max_slope_deg", message: "Input should be greater than 0" }]);
  state = formReducer(state, { type: "mode_chosen", mode: "time-based" });
  expect(valuesToSend(state)).toEqual({ mode: "time-based", voxel_size: 2 });
  expect(state.valuesResetByModeChange).toEqual({ settings: ["max_slope_deg"], mode: "time-based" });
});

test("a value carried to the new mode that its save refuses goes back to the default, and the form saves again", () => {
  let state = storedProjectState({ mode: "daylight" });
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 0.5, north_deg: 20 } });
  state = formReducer(state, { type: "save_succeeded", reply: { settings: { mode: "daylight", voxel_size: 0.5, north_deg: 20 }, grid_plan: null } });
  state = formReducer(state, { type: "mode_chosen", mode: "time-based" });
  const changeCount = state.changeCount;
  state = reject(state, [{ field: "voxel_size", message: "Input should be greater than or equal to 1" }]);
  expect(valuesToSend(state)).toEqual({ mode: "time-based", north_deg: 20 });
  expect(state.fieldErrors).toEqual({});
  expect(state.valuesResetByModeChange).toEqual({ settings: ["voxel_size"], mode: "time-based" });
  expect(state.pendingSave).toBe(true);
  expect(state.changeCount).toBe(changeCount + 1);
  // The next refusal is the new mode's own: nothing more is dropped.
  state = reject(state, [{ field: "north_deg", message: "Input should be less than 360" }]);
  expect(valuesToSend(state)).toEqual({ mode: "time-based", north_deg: 20 });
  expect(state.fieldErrors).toEqual({ north_deg: "Input should be less than 360" });
  // A change of the user ends the note.
  state = formReducer(state, { type: "values_changed", values: { north_deg: 10 } });
  expect(state.valuesResetByModeChange).toBeNull();
});

test("an error on a setting the mode does not show is said for the step with the setting's name", () => {
  let state = storedProjectState({ mode: "time-based", edge_taper: -1, voxel_size: 2 });
  state = reject(state, [{ field: "edge_taper", message: "Input should be greater than or equal to 0" }]);
  expect(state.fieldErrors).toEqual({});
  expect(state.stepErrors).toEqual(["Edge strip with less weight: Input should be greater than or equal to 0"]);
});

test("the form knows when its mode or analysis settings are not the stored ones: a save waits or was refused", () => {
  let state = storedProjectState({ mode: "daylight" });
  expect(analysisDiffersFromStored(state)).toBe(false);
  state = formReducer(state, { type: "mode_chosen", mode: "time-based" });
  expect(analysisDiffersFromStored(state)).toBe(true);           // the save waits
  state = reject(state, [{ field: null, message: "Value error, the settings do not fit together" }]);
  expect(analysisDiffersFromStored(state)).toBe(true);           // refused: the service still holds Daylight
  expect(state.storedAnalysisRevision).toBe(0);
  state = formReducer(state, { type: "save_succeeded", reply: { settings: { mode: "time-based" }, grid_plan: null } });
  expect(analysisDiffersFromStored(state)).toBe(false);
  expect(state.storedAnalysisRevision).toBe(1);                  // the stored analysis changed: its stage status is to come
  // A carving setting is not one the analysis reads.
  state = formReducer(state, { type: "values_changed", values: { carve_fraction: 0.5 } });
  expect(analysisDiffersFromStored(state)).toBe(false);
  state = formReducer(state, { type: "save_succeeded", reply: { settings: { mode: "time-based", carve_fraction: 0.5 }, grid_plan: null } });
  expect(state.storedAnalysisRevision).toBe(1);
  // A value typed back to the stored one is no change.
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 1.0 } });
  expect(analysisDiffersFromStored(state)).toBe(false);
  state = formReducer(state, { type: "values_changed", values: { voxel_size: 2.0 } });
  expect(analysisDiffersFromStored(state)).toBe(true);
});

test("a stored setting the engine ignores in the mode is not sent again; one the engine's analysis reads in every mode is kept", () => {
  // The balance temperature belongs to Solar usefulness only: the engine leaves it out of every other mode.
  expect(valuesToSend(storedProjectState({ mode: "time-based", balance_temperature: 99, voxel_size: 2 }))).toEqual({ mode: "time-based", voxel_size: 2 });
  // The edge strip has no field in Solar time-based, but the engine's analysis reads it in every mode: dropping it would make
  // the analysis out of date behind the form's back, so it is sent as stored.
  const state = storedProjectState({ mode: "time-based", edge_taper: 0.3 });
  expect(valuesToSend(state)).toEqual({ mode: "time-based", edge_taper: 0.3 });
  expect(analysisDiffersFromStored(state)).toBe(false);
});

test("a voxel size change sends the voxel size alone: the engine's sample spacing follows it (half the voxel size)", () => {
  const state = formReducer(storedProjectState({ mode: "daylight" }), { type: "values_changed", values: { voxel_size: 0.5 } });
  expect(valuesToSend(state)).toEqual({ mode: "daylight", voxel_size: 0.5 });
});
