// The state of the settings form: the values the user set, the starting values of the chosen mode, the errors of the last save
// and the voxel grid it planned. The service stores only the settings that were given (the engine warns about a setting the
// mode does not read), so the form sends the mode and the values the user set, never every field; the mode's starting values
// and the schema defaults fill the rest, on the service as in the form.
import { useEffect, useMemo, useReducer } from "react";
import { ApiError, putConfig, type ConfigErrorReply, type ConfigReply, type GridPlanReply, type ModeInfo } from "../api_client/client";
import { settingIsReadBy } from "./presentation";

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
  $ref?: string;
}

export interface FormState {
  mode: string;
  /** The settings the user set, which are what a save sends besides the mode. */
  userValues: Record<string, unknown>;
  startingValuesByMode: Record<string, Record<string, unknown>>;
  schemaProperties: Record<string, SchemaProperty>;
  /** The messages of the last rejected save, by setting name. */
  fieldErrors: Record<string, string>;
  /** Messages of the last rejected save that name no single setting (grid_step above voxel_size), shown for the step. */
  stepErrors: string[];
  gridPlan: GridPlanReply | null;
  /** A change has not been saved yet. */
  pendingSave: boolean;
  /** Counts the changes; each new count starts a save. */
  changeCount: number;
  /** Why the last save failed when the service did not answer with field errors (a run in progress, the engine stopped). */
  saveFailure: unknown;
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
  | { type: "save_failed"; error: unknown };

const sameValue = (first: unknown, second: unknown) => JSON.stringify(first) === JSON.stringify(second);

function startingValuesOf(state: Pick<FormState, "startingValuesByMode" | "mode">): Record<string, unknown> {
  return state.startingValuesByMode[state.mode] ?? {};
}

/** The form for a project's stored settings: the stored values that differ from the mode's starting values are the user's. */
export function initialFormState({ schema, modes, settings, gridPlan }: FormStart): FormState {
  const schemaProperties = (schema.properties ?? {}) as Record<string, SchemaProperty>;
  const startingValuesByMode = Object.fromEntries(modes.map((mode) => [mode.name, mode.starting_values]));
  const mode = typeof settings.mode === "string" ? settings.mode : String(schemaProperties.mode?.default);
  const startingValues = startingValuesByMode[mode] ?? {};
  const userValues = Object.fromEntries(Object.entries(settings).filter(([name, value]) =>
    name !== "mode" && !(name in startingValues && sameValue(value, startingValues[name]))));
  return { mode, userValues, startingValuesByMode, schemaProperties, fieldErrors: {}, stepErrors: [], gridPlan,
           pendingSave: false, changeCount: 0, saveFailure: null };
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
      return { ...state, userValues, pendingSave: true, changeCount: state.changeCount + 1, saveFailure: null };
    }
    case "mode_chosen": {
      const startingValues = state.startingValuesByMode[action.mode] ?? {};
      const userValues = Object.fromEntries(Object.entries(state.userValues).filter(([name]) =>
        settingIsReadBy(name, action.mode) && !(name in startingValues) && !SETTINGS_OF_ONE_MODE_ONLY.has(name)));
      return { ...state, mode: action.mode, userValues, pendingSave: true, changeCount: state.changeCount + 1, saveFailure: null };
    }
    case "save_succeeded":
      return { ...state, gridPlan: action.reply.grid_plan, fieldErrors: {}, stepErrors: [], pendingSave: false, saveFailure: null };
    case "save_rejected": {
      const fieldErrors: Record<string, string> = {};
      const stepErrors: string[] = [];
      for (const { field, message } of action.reply.field_errors) {
        if (field === null) stepErrors.push(message);
        else fieldErrors[field] = field in fieldErrors ? `${fieldErrors[field]} ${message}` : message;
      }
      return { ...state, fieldErrors, stepErrors, gridPlan: action.reply.grid_plan, pendingSave: false, saveFailure: null };
    }
    case "save_failed":
      return { ...state, pendingSave: false, saveFailure: action.error };
  }
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

export interface ConfigSaver {
  /** Saves *values* once no other change has come for the delay. */
  schedule: (values: Record<string, unknown>) => void;
  /** Drops the waiting save and any reply still to come. */
  cancel: () => void;
}

/**
 * Sends the latest values a delay after the last change. A reply is passed on only when no change has come since its request,
 * so an older save that answers late cannot overwrite the errors or grid plan of a newer one.
 */
export function createConfigSaver(save: (values: Record<string, unknown>) => Promise<ConfigReply>, dispatch: (action: FormAction) => void,
                                  delayMilliseconds = SAVE_DELAY_MILLISECONDS): ConfigSaver {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let latestChange = 0;
  const send = async (values: Record<string, unknown>, change: number) => {
    try {
      const reply = await save(values);
      if (change === latestChange) dispatch({ type: "save_succeeded", reply });
    } catch (error) {
      if (change !== latestChange) return;
      if (error instanceof ApiError && error.status === 422 && isConfigErrorReply(error.body)) dispatch({ type: "save_rejected", reply: error.body });
      else dispatch({ type: "save_failed", error });
    }
  };
  return {
    schedule: (values) => {
      clearTimeout(timer);
      const change = ++latestChange;
      timer = setTimeout(() => send(values, change), delayMilliseconds);
    },
    cancel: () => {
      clearTimeout(timer);
      latestChange++;
    },
  };
}

/** The form of one project: every change is saved with PUT config 400 ms after the last one. */
export function useSettingsForm(token: string, project: string, start: FormStart) {
  const [form, dispatch] = useReducer(formReducer, start, initialFormState);
  const saver = useMemo(() => createConfigSaver((values) => putConfig(token, project, values), dispatch), [token, project]);
  useEffect(() => saver.cancel, [saver]);
  // Only a change starts a save: a reply changes the form too, but not its change count.
  useEffect(() => {
    if (form.changeCount > 0) saver.schedule(valuesToSend(form));
  }, [form.changeCount, saver]);
  return { form, dispatch };
}
