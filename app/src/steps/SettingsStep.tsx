// The analysis settings (UX 5.4, 11), drawn by Site and grid (the shared ones) and by a criterion's panel (its own): the settings in
// their groups, the grid under Voxel size, the grid-over-budget message in place of the engine's, and messages that name no single
// setting. Run analysis (RunAnalysisButton) is pinned at the bottom of the panel in Site and grid and ends a criterion's panel,
// disabled with the first reason that blocks the run, its run's progress under it. Above the groups, after a weather file is added
// or replaced in this session, the notice of the period it may call for (weather_change_notice.ts).
import { useId, type ReactNode } from "react";
import { ApiError, refusalDetailOf, serviceProblemOf, type HealthReply } from "../api_client/client";
import { messages } from "../messages";
import {
  changedPeriodSettings, periodInWords, type AnalysisPeriodField, type ColdPeriodState, type Hemisphere,
} from "../settings_form/analysis_period";
import { shownValue, type FormState, type SaveOutcome } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS, fieldSettingOf, SETTING_PRESENTATIONS, settingsForStep, settingView, type StepName as FormStepName } from "../settings_form/presentation";
import { fieldErrorOf, gridLineOf, SettingField, WarningIcon, type SettingFieldExtras } from "../settings_form/SettingField";
import { SettingGroup } from "../settings_form/SettingGroup";
import { gridIsOverBudget, smallestVoxelSizeWithinBudget } from "./grid_budget";
import type { StepName } from "./step_summaries";
import type { WeatherChangeSuggestion } from "./weather_change_notice";
import "./steps.css";

export interface RunAnalysisConditions {
  runActive: boolean;
  maxVolumeFiles: number;
  testSurfaceFiles: number;
  modeNeedsWeatherFile: boolean;
  hasWeatherFile: boolean;
  form: Pick<FormState, "mode" | "fieldErrors">;
  /** The messages that name no setting, by the step that shows them (the shared form's in Site and grid, the criterion's in Criteria). */
  stepErrorsByStep: Partial<Record<StepName, readonly string[]>>;
  warmUpState: HealthReply["warm_up"]["state"] | null;
  /** The settings that belong to a criterion (GET criterion-keys), for the step that shows a setting to fix. */
  criterionKeys: ReadonlySet<string>;
  /** The step whose button says the reason: a setting to fix in another step is named with that step. */
  shownIn: StepName;
}

/**
 * The step that draws a setting's field: Site and grid for a shared analysis setting, Criteria for a criterion's and for the
 * carving, Envelope and massing and Export for theirs; null for a name the form does not show.
 */
export function stepOfSetting(name: string, criterionKeys: ReadonlySet<string>): StepName | null {
  const shownName = fieldSettingOf(name);
  const formStep = SETTING_PRESENTATIONS[shownName]?.step;
  if (formStep === undefined) return null;
  if (formStep === "settings") return criterionKeys.has(shownName) ? "criteria" : "site_and_grid";
  return formStep === "carving" ? "criteria" : formStep;
}

/** The label of a setting as the form shows it; settings drawn as one field have its label (the six period settings, "Analysis period"). */
function shownLabelOf(settingName: string, mode: string): string {
  return settingView(fieldSettingOf(settingName), mode).label;
}

/** Why Run analysis cannot start, the first of: a run, the inputs, the weather file, a setting, the warm-up; null when it can. */
export function runAnalysisBlocker(conditions: RunAnalysisConditions): string | null {
  const { form } = conditions;
  if (conditions.runActive) return messages.runInProgress;
  const hasMaxVolume = conditions.maxVolumeFiles > 0, hasTestSurfaces = conditions.testSurfaceFiles > 0;
  if (!hasMaxVolume && !hasTestSurfaces) return messages.addMaxVolumeAndTestSurfacesToRun;
  if (!hasMaxVolume) return messages.addMaxVolumeToRun;
  if (!hasTestSurfaces) return messages.addTestSurfacesToRun;
  if (conditions.modeNeedsWeatherFile && !conditions.hasWeatherFile) return messages.weatherFileNeeded;
  const firstFieldWithError = Object.keys(form.fieldErrors)[0];
  if (firstFieldWithError !== undefined) {
    // A setting of another step is named with its step, so the user knows where to find it.
    const step = stepOfSetting(firstFieldWithError, conditions.criterionKeys) ?? conditions.shownIn;
    const label = shownLabelOf(firstFieldWithError, form.mode);
    return step === conditions.shownIn ? messages.fixSettingToRun(label) : messages.fixSettingInStepToRun(label, messages.stepTitles[step]);
  }
  // A message that names no setting is shown above the settings of its step: "above" there, the step named elsewhere.
  const stepsWithMessages = (Object.keys(conditions.stepErrorsByStep) as StepName[]).filter((step) => (conditions.stepErrorsByStep[step] ?? []).length > 0);
  if (stepsWithMessages.includes(conditions.shownIn)) return messages.fixSettingsToRun;
  if (stepsWithMessages.length > 0) return messages.fixSettingsInStepToRun(messages.stepTitles[stepsWithMessages[0]]);
  // A warm-up that failed blocks nothing: a run then reports the problem itself (the service's warm-up says the same).
  if (conditions.warmUpState === null || conditions.warmUpState === "not_started" || conditions.warmUpState === "running") return messages.runButtonWaitsForGpu;
  return null;
}

/**
 * Saves a change still waiting (or a change whose save failed, again), then starts the run only when the settings it will read
 * are the ones the form shows: not after a refused or failed save, nor when the change was dropped. Resolves with whether the
 * run was started.
 */
export async function runAnalysisAfterSaving(flushSave: () => Promise<SaveOutcome>, startRun: () => void): Promise<boolean> {
  const outcome = await flushSave();
  if (outcome !== "saved" && outcome !== "none") return false;
  startRun();
  return true;
}

export interface SaveFailureText {
  /** Why, as far as the page knows: a run it does not know of, or the service's words; null when it gave none. */
  reason: string | null;
  advice: string;
}

/**
 * What the panel says about a save that failed without field errors (FormState.saveFailure); null without one, and for a
 * stopped engine or a lost token, which the app's overlay reports.
 */
export function saveFailureTextOf(saveFailure: unknown): SaveFailureText | null {
  if (saveFailure === null || serviceProblemOf(saveFailure) !== "other") return null;
  // A run the page did not start: one from before a reload, or from another tab.
  if (saveFailure instanceof ApiError && saveFailure.status === 409) return { reason: messages.runOfProjectElsewhere, advice: messages.saveAgainAfterThatRun };
  return { reason: refusalDetailOf(saveFailure), advice: messages.saveAgainOrRun };
}

/** The failed save, pinned under the step list whichever step is open, with Save again. */
export function SaveFailureNotice({ text, onSaveAgain }: { text: SaveFailureText; onSaveAgain: () => void }) {
  return (
    <div className="save-failure" role="alert">
      <p className="setting-error"><WarningIcon /><span>{messages.settingsNotSaved}</span></p>
      <p className="step-reason">{text.reason === null ? text.advice : `${text.reason} ${text.advice}`}</p>
      <button type="button" className="secondary-button" onClick={onSaveAgain}>{messages.saveAgain}</button>
    </div>
  );
}

type FormErrors = Pick<FormState, "fieldErrors" | "stepErrors">;

/**
 * The settings to fix of each step (UX 4.1, 11): the fields with an error of either form, counted in the step that draws them (the
 * six period settings are one field, as are the balance temperature and its dead band), and the messages that name no field,
 * counted where they are shown: the shared settings' in Site and grid, the criterion's in Criteria.
 */
export function settingsToFixByStep(shared: FormErrors, criterion: FormErrors, criterionKeys: ReadonlySet<string>): Partial<Record<StepName, number>> {
  const fields = new Set([...Object.keys(shared.fieldErrors), ...Object.keys(criterion.fieldErrors)].map(fieldSettingOf));
  const counts: Partial<Record<StepName, number>> = {};
  const count = (step: StepName, added: number) => { if (added > 0) counts[step] = (counts[step] ?? 0) + added; };
  for (const name of fields) count(stepOfSetting(name, criterionKeys) ?? "site_and_grid", 1);
  count("site_and_grid", shared.stepErrors.length);
  count("criteria", criterion.stepErrors.length);
  return counts;
}

/** All the settings to fix of a form: its fields with an error and its messages that name no field. */
export function settingsToFixCount(form: FormErrors): number {
  return new Set(Object.keys(form.fieldErrors).map(fieldSettingOf)).size + form.stepErrors.length;
}

interface SettingsToFixProps {
  /** The part of the form whose fields to show (Envelope and massing, Export, a criterion's carving rule). */
  step: FormStepName;
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  disabledReason: string | null;
}

/** The fields of *step* that hold an error, for a step that cannot be used yet: its own content is not shown, these are. */
export function SettingsToFix({ step, form, onChange, disabledReason }: SettingsToFixProps) {
  const views = settingsForStep(step, form.mode).flatMap((group) => [...group.essential, ...group.folded])
    .filter((view) => fieldErrorOf(form, view) !== undefined);
  if (views.length === 0) return null;
  return (
    <div className="settings-to-fix">
      {views.map((view) => <SettingField key={view.name} view={view} form={form} onChange={onChange} disabled={disabledReason !== null} />)}
    </div>
  );
}

// The engine samples the test surfaces at half the voxel size (pydantic_schemas.py, GRID_STEP_PER_VOXEL_SIZE_WHEN_UNSET); the
// interface does not set the spacing. SettingsStep.test.tsx checks the engine still says so.
const SAMPLE_SPACING_PER_VOXEL_SIZE = 0.5;

/** "Test surfaces sampled every 0.5 m", for the voxel size shown; null while it is not a number. */
function sampleSpacingLineOf(form: FormState): string | null {
  const voxelSize = shownValue(form, "voxel_size");
  return typeof voxelSize === "number" ? messages.testSurfacesSampledEvery(voxelSize * SAMPLE_SPACING_PER_VOXEL_SIZE) : null;
}

/**
 * The lines under Voxel size: the grid line, or the over-budget message in the place of the error, then the sample spacing the
 * engine uses. A refused save keeps the last grid planned, so the grid line stays under an error too; while the voxel size shown
 * is not the one planned (its save was refused), it says so.
 */
function voxelSizeExtras(form: FormState): SettingFieldExtras {
  const sampleSpacingLine = sampleSpacingLineOf(form);
  const plan = form.gridPlan;
  const gridLine = plan !== null && !gridIsOverBudget(plan) ? gridLineOf(form) : null;
  const notes = [gridLine, sampleSpacingLine].filter((line) => line !== null);
  if (plan === null || !gridIsOverBudget(plan)) return { notes };
  const text = messages.gridOverBudget(plan.resolution, plan.total_voxels, plan.budget_voxels,
    smallestVoxelSizeWithinBudget(plan.voxel_size, plan.total_voxels, plan.budget_voxels));
  return { notes, errorContent: <>{text.description} <strong>{text.advice}</strong></> };
}

/** The words of the notice of a new weather file: what the file means for the period, and the button that applies the offer. */
function weatherChangeTextOf(suggestion: WeatherChangeSuggestion): { text: string; useLabel: string } {
  if (suggestion.kind === "six_months") {
    return { text: messages.weatherChangeOtherHemisphere(suggestion.location, suggestion.hemisphere, periodInWords(suggestion.suggested)),
             useLabel: messages.shiftBySixMonthsButton };
  }
  const { coldDates, current } = suggestion;
  const coldDatesText = messages.periodDates(coldDates.startMonth, coldDates.startDay, coldDates.endMonth, coldDates.endDay);
  const currentDatesText = messages.periodDates(current.startMonth, current.startDay, current.endMonth, current.endDay);
  return { text: messages.weatherChangeColdPeriod(suggestion.location, coldDatesText, currentDatesText), useLabel: messages.useColdPeriodButton };
}

/** The notice of a weather file added or replaced in this session, with the period it offers; either button ends it. */
export interface WeatherChangeNoticeContent {
  suggestion: WeatherChangeSuggestion;
  onDismiss: () => void;
}

interface WeatherChangeNoticeProps extends WeatherChangeNoticeContent {
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  disabled: boolean;
}

/** The offer applies as a change in the period control does: the changed period settings, through the form's saver. */
function WeatherChangeNotice({ suggestion, onDismiss, form, onChange, disabled }: WeatherChangeNoticeProps) {
  const { text, useLabel } = weatherChangeTextOf(suggestion);
  const useSuggestedPeriod = () => {
    const values = Object.fromEntries(ANALYSIS_PERIOD_FIELDS.map((name) => [name, shownValue(form, name)])) as Record<AnalysisPeriodField, number | null>;
    onChange(changedPeriodSettings(values, suggestion.suggested));
    onDismiss();
  };
  return (
    <div className="weather-change-notice">
      <p>{text}</p>
      <div className="weather-change-notice-buttons">
        <button type="button" className="secondary-button" disabled={disabled} onClick={useSuggestedPeriod}>{useLabel}</button>
        <button type="button" className="secondary-button" disabled={disabled} aria-label={messages.keepAnalysisPeriodName} onClick={onDismiss}>
          {messages.keepAnalysisPeriodButton}
        </button>
      </div>
    </div>
  );
}

interface SettingsStepProps {
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  /** Why the settings cannot be changed now (a run is in progress: the service refuses to save); null when they can. */
  disabledReason: string | null;
  /** The cold period of the weather file, for the period's preset; null in the modes without one. */
  coldPeriod?: ColdPeriodState | null;
  /** The hemisphere of the weather file, for the period's heating season preset; northern without one. */
  hemisphere?: Hemisphere;
  /** The notice of a weather file added or replaced in this session; null when there is none to show. */
  weatherChangeNotice?: WeatherChangeNoticeContent | null;
  /** The input roles the project has files for: Account for context blocking shows only with surroundings or terrain. */
  inputRoles?: readonly string[];
  /** Which settings to draw: the shared ones (Site and grid) or a criterion's (its panel); absent, all. */
  settingShown?: (name: string) => boolean;
  /** The messages that name no setting to show here (those of the form these settings are saved by); absent, the form's. */
  stepErrors?: readonly string[];
  /** Whether the reason things are disabled is written here; false where another part says it (a criterion's Run analysis). */
  showsDisabledReason?: boolean;
}

const NO_INPUT_ROLES: readonly string[] = [];

export function SettingsStep({ form, onChange, disabledReason, coldPeriod = null, hemisphere = "northern", weatherChangeNotice = null,
                               inputRoles = NO_INPUT_ROLES, settingShown, stepErrors = form.stepErrors, showsDisabledReason = true }: SettingsStepProps) {
  const fieldExtras = { voxel_size: voxelSizeExtras(form), [ANALYSIS_PERIOD_FIELDS[0]]: { coldPeriod, hemisphere } };
  return (
    <div className="settings-step">
      {disabledReason !== null && showsDisabledReason && <p className="step-reason">{disabledReason}</p>}
      {/* A live region on the page from the start, so that screen readers announce the notice that fills it. */}
      <div className="weather-change-region" role="status">
        {weatherChangeNotice !== null && (
          <WeatherChangeNotice {...weatherChangeNotice} form={form} onChange={onChange} disabled={disabledReason !== null} />
        )}
      </div>
      {stepErrors.map((error) => <p key={error} className="setting-error step-error"><WarningIcon /><span>{error}</span></p>)}
      {settingsForStep("settings", form.mode, inputRoles, settingShown).map((group) => (
        <SettingGroup key={group.title} group={group} form={form} onChange={onChange} disabled={disabledReason !== null} fieldExtras={fieldExtras} />
      ))}
    </div>
  );
}

interface RunAnalysisButtonProps {
  blocker: string | null;
  onRunAnalysis: () => void;
  /** The button's text; Run analysis unless the step's button runs other stages (Build envelope and massing). */
  label?: string;
  /** The progress and outcome of the run the button started (RunProgress). */
  feedback?: ReactNode;
}

/** A step's run button, pinned under the step list, with the reason it is disabled and the progress of its run under it. */
export function RunAnalysisButton({ blocker, onRunAnalysis, label = messages.runAnalysis, feedback }: RunAnalysisButtonProps) {
  const reasonId = useId();
  return (
    <div className="run-button-area">
      <button type="button" className="primary-button" disabled={blocker !== null} aria-describedby={blocker !== null ? reasonId : undefined}
              onClick={onRunAnalysis}>
        {label}
      </button>
      {blocker !== null && <p id={reasonId} className="run-button-reason">{blocker}</p>}
      {feedback}
    </div>
  );
}
