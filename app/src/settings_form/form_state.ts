// The state of the settings form: the values the user set, the starting values of the chosen mode, the errors of the last save
// and the voxel grid it planned. The service stores only the settings that were given (the engine warns about a setting the
// mode does not read), so the form sends the mode and the values the user set, never every field; the mode's starting values
// and the schema defaults fill the rest, on the service as in the form.
import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError, putConfig, type ConfigErrorReply, type ConfigReply, type GridPlanReply, type ModeInfo } from "../api_client/client";
import { gridIsOverBudget } from "../steps/grid_budget";
import { errorOfHiddenSetting, shownConfigErrorOf } from "./engine_errors";
import { SETTING_PRESENTATIONS, settingIsReadBy } from "./presentation";

export const SAVE_DELAY_MILLISECONDS = 400;

// A threshold is a cutoff on one mode's scores (m²·h in time-based, relative scores in the weighted modes, which may also
// name a method the others cannot use), so it never carries over to another mode.
const SETTINGS_OF_ONE_MODE_ONLY = new Set(["threshold"]);

/** One property of the engine's config schema (GET schema), as much of it as the form reads. */
export interface SchemaProperty {
  type?: string;
  default?: unknown;
  enum?: unknown[];
  anyOf?: SchemaProperty[];
  items?: SchemaProperty;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  $ref?: string;
}

export interface FormState {
  mode: string;
  /** The settings the user set, which are what a save sends besides the mode. */
  userValues: Record<string, unknown>;
  startingValuesByMode: Record<string, Record<string, unknown>>;
  /** How each mode scores ("weighted_sum", "violation_count"): some automatic values depend on it (the slope limit). */
  scoreKindByMode: Record<string, string>;
  schemaProperties: Record<string, SchemaProperty>;
  /** The messages of the last rejected save, by setting name. */
  fieldErrors: Record<string, string>;
  /** Messages of the last rejected save that name no setting the form shows (a missing weather file), shown for the step. */
  stepErrors: string[];
  gridPlan: GridPlanReply | null;
  /** A change has not been saved yet. */
  pendingSave: boolean;
  /** Counts the changes; each new count starts a save. */
  changeCount: number;
  /** Why the last save failed when the service did not answer with field errors (a run in progress, the engine stopped). */
  saveFailure: unknown;
  /**
   * The values the user set that the last mode change carried over, until the new mode's first save answers: a value it
   * refuses goes back to the new mode's own (UX 5.3, choosing a mode fills its starting values).
   */
  carriedValues: Record<string, unknown>;
  /** The settings the last mode change set back to the new mode's own value, as the new mode refused the user's; null when none. */
  valuesResetByModeChange: { settings: string[]; mode: string } | null;
  /**
   * The settings the service holds (config.yaml): those the project opened with, then those of the last save it stored. The
   * stage status and the results describe these, which are not the form's while a save waits or after one was refused.
   */
  stored: { mode: string; values: Record<string, unknown> };
  /** Counts the stored saves that changed what the analysis reads (the mode, a setting of the Settings step). */
  storedAnalysisRevision: number;
}

export interface FormStart {
  schema: Record<string, unknown>;          // the reply of GET schema
  modes: ModeInfo[];                        // the reply of GET modes
  settings: Record<string, unknown>;        // the project's stored settings, as the service gives them
  gridPlan: GridPlanReply | null;
}

export type FormAction =
  | { type: "values_changed"; values: Record<string, unknown> }
  | { type: "mode_chosen"; mode: string }
  | { type: "save_succeeded"; reply: ConfigReply }
  | { type: "save_rejected"; reply: ConfigErrorReply }
  | { type: "save_failed"; error: unknown }
  | { type: "project_opened"; start: FormStart };

const sameValue = (first: unknown, second: unknown) => JSON.stringify(first) === JSON.stringify(second);

function startingValuesOf(state: Pick<FormState, "startingValuesByMode" | "mode">): Record<string, unknown> {
  return state.startingValuesByMode[state.mode] ?? {};
}

/** The form for a project's stored settings: the stored values that differ from the mode's starting values are the user's. */
export function initialFormState({ schema, modes, settings, gridPlan }: FormStart): FormState {
  const schemaProperties = (schema.properties ?? {}) as Record<string, SchemaProperty>;
  const startingValuesByMode = Object.fromEntries(modes.map((mode) => [mode.name, mode.starting_values]));
  const scoreKindByMode = Object.fromEntries(modes.map((mode) => [mode.name, mode.score_kind]));
  const mode = typeof settings.mode === "string" ? settings.mode : String(schemaProperties.mode?.default);
  const startingValues = startingValuesByMode[mode] ?? {};
  // A stored setting the mode does not read (left from another mode, or written by hand) is not sent again: the engine would
  // ignore it, but still refuse it when invalid, with no field in this mode to fix it in.
  const userValues = Object.fromEntries(Object.entries(settings).filter(([name, value]) =>
    name !== "mode" && settingIsReadBy(name, mode) && !(name in startingValues && sameValue(value, startingValues[name]))));
  // Stored settings whose grid is over the budget (a larger maximum volume came after them) open with Voxel size to fix, as a
  // save of them would be refused; the message under the field is the step's own (SettingsStep), so the text here stays empty.
  const fieldErrors: Record<string, string> = gridIsOverBudget(gridPlan) ? { voxel_size: "" } : {};
  return { mode, userValues, startingValuesByMode, scoreKindByMode, schemaProperties, fieldErrors, stepErrors: [], gridPlan,
           pendingSave: false, changeCount: 0, saveFailure: null, carriedValues: {}, valuesResetByModeChange: null,
           stored: { mode, values: userValues }, storedAnalysisRevision: 0 };
}

/**
 * A changed value replaces the user's; null unsets it, so the mode's starting value or the default applies again.
 * A new mode brings its starting values and keeps the settings the user set that it reads and does not start with.
 */
export function formReducer(state: FormState, action: FormAction): FormState {
  switch (action.type) {
    case "values_changed": {
      const userValues = { ...state.userValues };
      for (const [name, value] of Object.entries(action.values)) {
        if (value === null || value === undefined) delete userValues[name];
        else userValues[name] = value;
      }
      const carriedValues = Object.fromEntries(Object.entries(state.carriedValues).filter(([name]) => !(name in action.values)));
      return { ...state, userValues, pendingSave: true, changeCount: state.changeCount + 1, saveFailure: null, carriedValues,
               valuesResetByModeChange: null };
    }
    case "mode_chosen": {
      const startingValues = state.startingValuesByMode[action.mode] ?? {};
      const kept = Object.entries(state.userValues).filter(([name]) =>
        settingIsReadBy(name, action.mode) && !(name in startingValues) && !SETTINGS_OF_ONE_MODE_ONLY.has(name));
      // A value the last save refused is not carried over: the new mode would refuse it too.
      const refused = kept.filter(([name]) => name in state.fieldErrors).map(([name]) => name);
      const carried = kept.filter(([name]) => !refused.includes(name));
      // The errors were the old mode's; the save of the new one brings its own, so none is left on a field this mode hides.
      return { ...state, mode: action.mode, userValues: Object.fromEntries(carried), pendingSave: true, changeCount: state.changeCount + 1,
               saveFailure: null, fieldErrors: {}, stepErrors: [], carriedValues: Object.fromEntries(carried),
               valuesResetByModeChange: refused.length > 0 ? { settings: refused, mode: action.mode } : null };
    }
    case "save_succeeded": {
      // The reply gives the settings stored; without a mode in it (an older service), the form's are the ones sent.
      const { mode: storedMode, ...storedValues } = action.reply.settings ?? {};
      const stored = typeof storedMode === "string" ? { mode: storedMode, values: storedValues } : { mode: state.mode, values: state.userValues };
      const analysisChanged = !sameAnalysisSettings(state, state.stored, stored);
      return { ...state, gridPlan: action.reply.grid_plan, fieldErrors: {}, stepErrors: [], pendingSave: false, saveFailure: null, carriedValues: {},
               stored, storedAnalysisRevision: state.storedAnalysisRevision + (analysisChanged ? 1 : 0) };
    }
    case "save_rejected": {
      const shownErrors = action.reply.field_errors.map(({ field, message }) => shownConfigErrorOf(field, message, state.mode));
      // The first save after a mode change: a value it carried over that the new mode refuses goes back to the mode's own,
      // and the form saves again without it.
      const carriedAndRefused = [...new Set(shownErrors.flatMap((shown) => shown.settings))].filter((name) =>
        name in state.carriedValues && name in state.userValues && sameValue(state.userValues[name], state.carriedValues[name]));
      const fieldErrors: Record<string, string> = {};
      const stepErrors: string[] = [];
      for (const shown of shownErrors) {
        if (shown.settings.some((name) => carriedAndRefused.includes(name))) continue;      // its value is gone
        // Under each setting the error names, in the interface's words (engine_errors.ts); one naming none is the step's,
        // as is one on a setting this mode does not show, with the setting's name.
        if (shown.settings.length === 0) stepErrors.push(shown.message);
        for (const setting of shown.settings) {
          if (!settingIsReadBy(setting, state.mode)) stepErrors.push(errorOfHiddenSetting(setting, shown.message, state.mode));
          else fieldErrors[setting] = setting in fieldErrors ? `${fieldErrors[setting]} ${shown.message}` : shown.message;
        }
      }
      if (carriedAndRefused.length > 0) {
        const userValues = Object.fromEntries(Object.entries(state.userValues).filter(([name]) => !carriedAndRefused.includes(name)));
        const resetSettings = [...(state.valuesResetByModeChange?.settings ?? []), ...carriedAndRefused];
        return { ...state, userValues, fieldErrors, stepErrors: [...new Set(stepErrors)], pendingSave: true, changeCount: state.changeCount + 1,
                 saveFailure: null, carriedValues: {}, valuesResetByModeChange: { settings: resetSettings, mode: state.mode } };
      }
      // A refusal plans no grid unless the grid is what it refuses (over the budget): the last grid planned stays, so the grid
      // line under Voxel size is not lost to an error elsewhere.
      const gridPlan = action.reply.grid_plan ?? (gridIsOverBudget(state.gridPlan) ? null : state.gridPlan);
      return { ...state, fieldErrors, stepErrors: [...new Set(stepErrors)], gridPlan, pendingSave: false, saveFailure: null, carriedValues: {} };
    }
    case "save_failed":
      return { ...state, pendingSave: false, saveFailure: action.error };
    case "project_opened":
      return initialFormState(action.start);
  }
}

// The settings preprocessing reads: those of the Settings step but the computer's (how rays are batched, the statistics).
const ANALYSIS_SETTINGS = Object.keys(SETTING_PRESENTATIONS).filter((name) =>
  SETTING_PRESENTATIONS[name].step === "settings" && SETTING_PRESENTATIONS[name].group !== "Computer");

type SettingsOfMode = FormState["stored"];

/** Whether two sets of settings give the analysis the same mode and the same values (the defaults of their mode filled in). */
function sameAnalysisSettings(state: FormState, first: SettingsOfMode, second: SettingsOfMode): boolean {
  if (first.mode !== second.mode) return false;
  const valueIn = (settings: SettingsOfMode, name: string) => shownValue({ ...state, mode: settings.mode, userValues: settings.values }, name);
  return ANALYSIS_SETTINGS.every((name) => sameValue(valueIn(first, name), valueIn(second, name)));
}

/**
 * Whether the form's mode or analysis settings differ from the stored ones (a save waits, or was refused): the analysis the
 * stage status calls current is then not the one of the settings shown, and the carving is locked as out of date (UX 5.5).
 */
export function analysisDiffersFromStored(state: FormState): boolean {
  return !sameAnalysisSettings(state, state.stored, { mode: state.mode, values: state.userValues });
}

/** What a save sends: the mode and the settings the user set. */
export function valuesToSend(state: FormState): Record<string, unknown> {
  return { ...state.userValues, mode: state.mode };
}

/** The value a setting has without the user: the mode's starting value, else the schema default (null when it has none). */
export function defaultValue(state: FormState, name: string): unknown {
  const startingValues = startingValuesOf(state);
  return name in startingValues ? startingValues[name] : (state.schemaProperties[name]?.default ?? null);
}

/** The value the form shows for a setting, in the engine's units. */
export function shownValue(state: FormState, name: string): unknown {
  return name in state.userValues ? state.userValues[name] : defaultValue(state, name);
}

function isConfigErrorReply(body: unknown): body is ConfigErrorReply {
  return typeof body === "object" && body !== null && Array.isArray((body as ConfigErrorReply).field_errors);
}

/**
 * How the last save sent ended: stored, refused with field errors (422), failed (a run in progress, the engine stopped),
 * overtaken by a newer change while it was on its way, or no save was sent at all.
 */
export type SaveOutcome = "saved" | "refused" | "failed" | "overtaken" | "none";

export interface ConfigSaver {
  /** Saves *values* once no other change has come for the delay. */
  schedule: (values: Record<string, unknown>) => void;
  /**
   * Sends the waiting save now, or sends a failed save again; resolves with how the save of the latest change ended, once its
   * reply is passed on ("none" when no save was sent). A save overtaken by a newer change resolves with that change's save.
   */
  flush: () => Promise<SaveOutcome>;
  /** Drops the waiting save and any reply still to come. */
  cancel: () => void;
}

interface SaveRequest {
  values: Record<string, unknown>;
  change: number;
}

/**
 * Sends the latest values a delay after the last change. A reply is passed on only when no change has come since its request,
 * so an older save that answers late cannot overwrite the errors or grid plan of a newer one.
 */
export function createConfigSaver(save: (values: Record<string, unknown>) => Promise<ConfigReply>, dispatch: (action: FormAction) => void,
                                  delayMilliseconds = SAVE_DELAY_MILLISECONDS): ConfigSaver {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let latestChange = 0;
  let waitingSave: SaveRequest | null = null;
  // The latest change, when its save failed without field errors (a run the page does not know of, a file the service could not
  // write): the next flush sends it again instead of answering with the old failure.
  let failedSave: SaveRequest | null = null;
  let lastSave: Promise<SaveOutcome> = Promise.resolve("none");
  const send = async (request: SaveRequest): Promise<SaveOutcome> => {
    try {
      const reply = await save(request.values);
      if (request.change !== latestChange) return "overtaken";
      dispatch({ type: "save_succeeded", reply });
      return "saved";
    } catch (error) {
      if (request.change !== latestChange) return "overtaken";
      if (error instanceof ApiError && error.status === 422 && isConfigErrorReply(error.body)) {
        dispatch({ type: "save_rejected", reply: error.body });
        return "refused";
      }
      failedSave = request;
      dispatch({ type: "save_failed", error });
      return "failed";
    }
  };
  const sendWaitingSave = () => {
    clearTimeout(timer);
    if (waitingSave !== null) {
      lastSave = send(waitingSave);
      waitingSave = null;
    }
    return lastSave;
  };
  const flush = async (): Promise<SaveOutcome> => {
    if (waitingSave === null && failedSave !== null) waitingSave = failedSave;
    failedSave = null;
    let saveToWaitFor = sendWaitingSave();
    for (;;) {
      const outcome = await saveToWaitFor;
      if (outcome !== "overtaken") return outcome;
      const newerSave = sendWaitingSave();      // the change that overtook it, sent now if it still waits
      if (newerSave === saveToWaitFor) return outcome;    // cancelled: no newer save to wait for
      saveToWaitFor = newerSave;
    }
  };
  return {
    schedule: (values) => {
      clearTimeout(timer);
      failedSave = null;
      waitingSave = { values, change: ++latestChange };
      timer = setTimeout(sendWaitingSave, delayMilliseconds);
    },
    flush,
    cancel: () => {
      clearTimeout(timer);
      waitingSave = null;
      failedSave = null;
      latestChange++;
    },
  };
}

/**
 * The form of the open project: every change is saved with PUT config 400 ms after the last one. Opening another project
 * starts its form from *start*, and a change still waiting is sent to the project it was made in, its reply not shown.
 * *flushSave* sends a waiting change at once and resolves, with how the save ended, when its reply is in the form, for a run
 * that must use it (a save that failed is sent again). *changeAndSave* makes a change and saves it with the changes before it at once, without the delay (the
 * carving threshold, whose run follows its save).
 */
export function useSettingsForm(token: string, project: string, start: FormStart) {
  const [form, dispatchToReact] = useReducer(formReducer, start, initialFormState);
  // The form after every action dispatched so far, ahead of the render that shows it, so a save made at once sends them all.
  const latestForm = useRef(form);
  const changeSavedAtOnce = useRef(0);
  const saver = useRef<ConfigSaver | null>(null);
  const currentToken = useRef(token);
  const formProject = useRef(project);

  const dispatch = useCallback((action: FormAction) => {
    latestForm.current = formReducer(latestForm.current, action);
    dispatchToReact(action);
  }, []);

  useEffect(() => {
    currentToken.current = token;      // a new token is used from the next save on; it starts no save of its own
  }, [token]);

  useEffect(() => {
    const projectSaver: ConfigSaver = createConfigSaver((values) => putConfig(currentToken.current, project, values),
      (action) => { if (saver.current === projectSaver) dispatch(action); });
    saver.current = projectSaver;
    return () => {
      saver.current = null;
      void projectSaver.flush();
    };
  }, [project]);

  useEffect(() => {
    if (formProject.current === project) return;
    formProject.current = project;
    changeSavedAtOnce.current = 0;
    dispatch({ type: "project_opened", start });     // the start given with the new project
  }, [project]);

  // Only a change starts a save: a reply changes the form too, but not its change count, and opening a project sets it to 0.
  // A change changeAndSave has sent already is not scheduled again.
  useEffect(() => {
    if (form.changeCount > changeSavedAtOnce.current) saver.current?.schedule(valuesToSend(form));
  }, [form.changeCount]);

  const flushSave = useCallback((): Promise<SaveOutcome> => saver.current?.flush() ?? Promise.resolve("none"), []);
  // The form after every action so far, for code that reads it after awaiting a save, before the render that shows it.
  const currentForm = useCallback(() => latestForm.current, []);
  const changeAndSave = useCallback((values: Record<string, unknown>): Promise<SaveOutcome> => {
    dispatch({ type: "values_changed", values });
    if (saver.current === null) return Promise.resolve("none");
    changeSavedAtOnce.current = latestForm.current.changeCount;
    saver.current.schedule(valuesToSend(latestForm.current));
    return saver.current.flush();
  }, []);
  return { form, dispatch, flushSave, changeAndSave, currentForm, pendingSave: form.pendingSave };
}
