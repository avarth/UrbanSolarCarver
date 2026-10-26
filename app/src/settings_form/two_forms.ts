// The shared settings and those of one criterion are two forms (ProjectWorkspace): the shared one saves with PUT shared-settings
// and owns the grid plan, the criterion's saves with PATCH criteria/{id} and holds the mode. Settings are split between them by
// the service's criterion keys (GET criterion-keys). Until the steps show the two apart, they see them as one form: each value
// read from the form that owns it, each change sent to it.
import { useEffect, useRef } from "react";
import type { ConfigErrorReply } from "../api_client/client";
import { shownConfigErrorOf } from "./engine_errors";
import { shownValue, storedValue, type FormAction, type FormState, type SaveOutcome, type SettingsForm } from "./form_state";

/** Settings split into the shared ones and those of a criterion (the mode among them), by the criterion keys (GET criterion-keys). */
export function splitSettings(values: Record<string, unknown>, criterionKeys: ReadonlySet<string>) {
  const shared: Record<string, unknown> = {}, criterion: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(values)) (criterionKeys.has(name) ? criterion : shared)[name] = value;
  return { shared, criterion };
}

/**
 * The shared settings' form and a criterion's as one form, for the steps that show the settings of both: each setting's value,
 * stored value and error are those of the form that owns it, the mode and its starting values the criterion's, the grid the
 * shared form's. A change waits, the analysis settings differ from the stored ones, or a save failed when either form says so.
 */
export function combinedForm(shared: FormState, criterion: FormState): FormState {
  return {
    ...criterion,
    userValues: { ...shared.userValues, ...criterion.userValues },
    fieldErrors: { ...shared.fieldErrors, ...criterion.fieldErrors },
    stepErrors: [...new Set([...shared.stepErrors, ...criterion.stepErrors])],
    gridPlan: shared.gridPlan,
    pendingSave: shared.pendingSave || criterion.pendingSave,
    changeCount: shared.changeCount + criterion.changeCount,
    saveFailure: shared.saveFailure ?? criterion.saveFailure,
    stored: { mode: criterion.stored.mode, values: { ...shared.stored.values, ...criterion.stored.values } },
    storedAnalysisRevision: shared.storedAnalysisRevision + criterion.storedAnalysisRevision,
  };
}

// The outcomes that keep a run from starting come first: of two saves, the first of these that either ended with is told.
const OUTCOMES_IN_ORDER: readonly SaveOutcome[] = ["failed", "refused", "overtaken", "saved", "none"];

/** How the saves of the two forms ended, as one: the first of failed, refused, overtaken, saved, none that either ended with. */
export function combinedSaveOutcome(outcomes: readonly SaveOutcome[]): SaveOutcome {
  return OUTCOMES_IN_ORDER.find((outcome) => outcomes.includes(outcome)) ?? "none";
}

/** The actions the steps dispatch to the settings: changes, a mode, the field errors of a failed run. */
export type StepFormAction = Extract<FormAction, { type: "values_changed" | "mode_chosen" | "save_rejected" }>;

type FieldError = ConfigErrorReply["field_errors"][number];

/**
 * Field errors split by the form that owns the settings each names, read as the form reads them (shownConfigErrorOf): one naming
 * settings of both forms goes to both, one naming none to the criterion's (a mode that needs a weather file).
 */
function splitFieldErrors(fieldErrors: readonly FieldError[], mode: string, criterionKeys: ReadonlySet<string>) {
  const shared: FieldError[] = [], criterion: FieldError[] = [];
  for (const error of fieldErrors) {
    const named = shownConfigErrorOf(error.field, error.message, mode).settings;
    if (named.some((name) => !criterionKeys.has(name))) shared.push(error);
    if (named.length === 0 || named.some((name) => criterionKeys.has(name))) criterion.push(error);
  }
  return { shared, criterion };
}

/** The calls of the two forms as one, for the steps that show the settings of both. */
export interface BothForms {
  /** The form the steps show (combinedForm). */
  form: FormState;
  dispatch: (action: StepFormAction) => void;
  flushSave: () => Promise<SaveOutcome>;
  changeAndSave: (values: Record<string, unknown>) => Promise<SaveOutcome>;
  cancelSave: () => void;
  currentForm: () => FormState;
}

/**
 * The shared settings' form and the selected criterion's as one: a change goes to the form of each setting it holds (an empty
 * one, which asks for a new grid plan, to the shared form), a mode to the criterion's, which the shared form follows, and a failed
 * run's field errors to the forms of the settings they name. Flushing flushes both; a change saved at once is saved by the form of
 * its settings (the carving's empty commit by the criterion's), with the other form's waiting change flushed with it.
 */
export function bothForms(shared: SettingsForm, criterion: SettingsForm, criterionKeys: ReadonlySet<string>): BothForms {
  const isEmpty = (values: Record<string, unknown>) => Object.keys(values).length === 0;
  const dispatch = (action: StepFormAction) => {
    switch (action.type) {
      case "values_changed": {
        const split = splitSettings(action.values, criterionKeys);
        if (!isEmpty(split.shared) || isEmpty(split.criterion)) shared.dispatch({ type: "values_changed", values: split.shared });
        if (!isEmpty(split.criterion)) criterion.dispatch({ type: "values_changed", values: split.criterion });
        return;
      }
      case "mode_chosen":
        criterion.dispatch(action);
        shared.dispatch({ type: "mode_followed", mode: action.mode });
        return;
      case "save_rejected": {
        // A run's errors; only the shared settings plan a grid.
        const split = splitFieldErrors(action.reply.field_errors, criterion.currentForm().mode, criterionKeys);
        if (split.shared.length > 0) shared.dispatch({ type: "save_rejected", reply: { ...action.reply, field_errors: split.shared } });
        if (split.criterion.length > 0) criterion.dispatch({ type: "save_rejected", reply: { ...action.reply, field_errors: split.criterion, grid_plan: null } });
        return;
      }
    }
  };
  const changeAndSave = async (values: Record<string, unknown>): Promise<SaveOutcome> => {
    const split = splitSettings(values, criterionKeys);
    const criterionSaves = !isEmpty(split.criterion) || isEmpty(split.shared);
    return combinedSaveOutcome(await Promise.all([
      isEmpty(split.shared) ? shared.flushSave() : shared.changeAndSave(split.shared),
      criterionSaves ? criterion.changeAndSave(split.criterion) : criterion.flushSave(),
    ]));
  };
  return {
    form: combinedForm(shared.form, criterion.form),
    dispatch,
    flushSave: async () => combinedSaveOutcome(await Promise.all([shared.flushSave(), criterion.flushSave()])),
    changeAndSave,
    cancelSave: () => {
      shared.cancelSave();
      criterion.cancelSave();
    },
    currentForm: () => combinedForm(shared.currentForm(), criterion.currentForm()),
  };
}

/**
 * Whether the shared form holds a change the service has not stored, with no save on its way: errors from its last save, or values
 * that are not the stored ones. The service checks the shared settings with every criterion, so such a save may have been refused
 * for a criterion's sake (its mode needs a weather file), and a save of the criterion can make it storable.
 */
export function sharedChangeHeldBack(shared: FormState): boolean {
  if (shared.pendingSave) return false;
  if (Object.keys(shared.fieldErrors).length > 0 || shared.stepErrors.length > 0) return true;
  const names = new Set([...Object.keys(shared.userValues), ...Object.keys(shared.stored.values)]);
  return [...names].some((name) => JSON.stringify(shownValue(shared, name)) !== JSON.stringify(storedValue(shared, name)));
}

/**
 * bothForms, and after each stored save of the criterion (a mode change among them) the shared form saves again when its change
 * was held back (sharedChangeHeldBack): nothing else would send it, and its errors would keep Run analysis blocked.
 */
export function useBothForms(shared: SettingsForm, criterion: SettingsForm, criterionKeys: ReadonlySet<string>): BothForms {
  // A stored save is the only action that gives the criterion's form new stored settings.
  const criterionStored = criterion.form.stored;
  const criterionStoredBefore = useRef(criterionStored);
  useEffect(() => {
    if (criterionStoredBefore.current === criterionStored) return;
    criterionStoredBefore.current = criterionStored;
    if (sharedChangeHeldBack(shared.currentForm())) shared.dispatch({ type: "values_changed", values: {} });
  }, [criterionStored]);
  return bothForms(shared, criterion, criterionKeys);
}
