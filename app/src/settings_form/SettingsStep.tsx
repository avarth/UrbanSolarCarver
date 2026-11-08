// The analysis settings (UX 5.4, 11), drawn by the project settings window (the shared ones, ProjectSettingsDialog) and by a
// criterion's panel (its own): the settings in their groups, the grid under Voxel size, the grid-over-budget message in place of the
// engine's, and messages that name no single setting. Run analysis (RunAnalysisButton) is pinned at the bottom of the panel in
// Criteria, with Build envelope and massing (CriteriaRunBar): disabled with the first reason that blocks the run, its run's progress
// under it. Above the groups, after a weather file is added or replaced in this session, the notice of the period it may call for
// (weather_change_notice.ts); a criterion's panel shows it under the header of its Settings section instead, open or closed
// (WeatherChangeRegion).
import { useId, type ReactNode } from "react";
import { ApiError, refusalDetailOf, serviceProblemOf, type HealthReply } from "../api_client/client";
import { messages } from "../messages";
import {
  changedPeriodSettings, periodInWords, type AnalysisPeriodField, type ColdPeriodState, type Hemisphere,
} from "./analysis_period";
import { shownValue, type FormState, type SaveOutcome } from "./form_state";
import {
  ANALYSIS_PERIOD_FIELDS, fieldSettingOf, SETTING_PRESENTATIONS, settingHasInputs, settingIsShownIn, settingsForStep, settingView,
  type StepName as FormStepName,
} from "./presentation";
import { fieldErrorOf, gridLineOf, SettingField, WarningIcon, type SettingFieldExtras } from "./SettingField";
import { SettingGroup } from "./SettingGroup";
import { gridIsOverBudget, smallestVoxelSizeWithinBudget } from "./grid_budget";
import type { SettingPlace, StepName } from "../stages";
import type { WeatherChangeSuggestion } from "./weather_change_notice";
import "../theme/panels.css";

export interface RunAnalysisConditions {
  runActive: boolean;
  /** The run under way is a simulation (Simulate's Run), which the reason names; absent: false. */
  simulationActive?: boolean;
  maxVolumeFiles: number;
  /** The test surface files of the criterion shown. */
  testSurfaceFiles: number;
  /** The name of another criterion that is on and protects nothing (the run refuses to start then); absent or null: none. */
  otherCriterionWithoutTestSurfaces?: string | null;
  /** Every criterion is bypassed: the run refuses to start. */
  noCriterionOn?: boolean;
  modeNeedsWeatherFile: boolean;
  /** The name of another criterion that is on whose mode needs a weather file (the run refuses without one); absent or null: none. */
  otherCriterionNeedingWeatherFile?: string | null;
  hasWeatherFile: boolean;
  form: Pick<FormState, "mode" | "fieldErrors">;
  /** The messages that name no setting, by the place that shows them (the shared form's in the project settings, the criterion's in Criteria). */
  stepErrorsByPlace: Partial<Record<SettingPlace, readonly string[]>>;
  warmUpState: HealthReply["warm_up"]["state"] | null;
  /** The settings that belong to a criterion (GET criterion-keys), for the place that shows a setting to fix. */
  criterionKeys: ReadonlySet<string>;
  /** The step whose button says the reason: a setting to fix in another place is named with that place. */
  shownIn: StepName;
  /**
   * The shown criterion's name, with several criteria: in Criteria the reasons about it (its test surfaces, its weather file, its
   * settings to fix) name it, as the reasons about another criterion do; absent or null: they do not.
   */
  shownCriterionName?: string | null;
}

/**
 * The place that draws a setting's field: the project settings window for a shared analysis setting, Criteria for a criterion's, the
 * mode and the carving, Envelope and massing and Export for theirs; null for a name the form does not show.
 */
export function placeOfSetting(name: string, criterionKeys: ReadonlySet<string>): SettingPlace | null {
  if (name === "mode") return "criteria";
  const shownName = fieldSettingOf(name);
  const formStep = SETTING_PRESENTATIONS[shownName]?.step;
  if (formStep === undefined) return null;
  if (formStep === "settings") return criterionKeys.has(shownName) ? "criteria" : "project_settings";
  return formStep === "carving" ? "criteria" : formStep;
}

/** The name of a place in the run's reasons: the step's title, or Settings for the project settings window. */
export function placeTitleOf(place: SettingPlace): string {
  return place === "project_settings" ? messages.projectSettingsPlace : messages.stepTitles[place];
}

/**
 * The label of a setting as the form shows it; settings drawn as one field have its label (the six period settings, "Analysis
 * period"); the mode, which has tiles and no label, is "Mode".
 */
export function shownLabelOf(settingName: string, mode: string): string {
  return settingName === "mode" ? messages.modeGroupLabel : settingView(fieldSettingOf(settingName), mode).label;
}

/** Why Run analysis cannot start, and the place of the settings to fix when they are not in the button's step. */
export interface RunAnalysisBlock {
  reason: string;
  /** The place that holds the setting to fix, when it is not the step of the button (the project settings window, a later step); else null. */
  settingsElsewhere: SettingPlace | null;
}

/** Why Run analysis cannot start, the first of: a run, the inputs, the weather file, a setting, the warm-up; null when it can. */
export function runAnalysisBlocker(conditions: RunAnalysisConditions): string | null {
  return runAnalysisBlockOf(conditions)?.reason ?? null;
}

/** As runAnalysisBlocker, with the place of a setting to fix that the reason names, so the button can lead there. */
export function runAnalysisBlockOf(conditions: RunAnalysisConditions): RunAnalysisBlock | null {
  const plain = (reason: string): RunAnalysisBlock => ({ reason, settingsElsewhere: null });
  const { form } = conditions;
  if (conditions.runActive) return plain(conditions.simulationActive === true ? messages.simulationInProgress : messages.runInProgress);
  if (conditions.noCriterionOn === true) return plain(messages.turnOnCriterionToRun);
  const hasMaxVolume = conditions.maxVolumeFiles > 0, hasTestSurfaces = conditions.testSurfaceFiles > 0;
  const criterionName = conditions.shownIn === "criteria" ? conditions.shownCriterionName ?? null : null;
  if (!hasMaxVolume && !hasTestSurfaces) return plain(messages.addMaxVolumeAndTestSurfacesToRun);
  if (!hasMaxVolume) return plain(messages.addMaxVolumeToRun);
  if (!hasTestSurfaces) return plain(criterionName === null ? messages.addTestSurfacesToRun : messages.addTestSurfacesOfCriterionToRun(criterionName));
  if (conditions.otherCriterionWithoutTestSurfaces != null) return plain(messages.addTestSurfacesOfCriterionToRun(conditions.otherCriterionWithoutTestSurfaces));
  if (conditions.modeNeedsWeatherFile && !conditions.hasWeatherFile) {
    return plain(criterionName === null ? messages.weatherFileNeeded : messages.weatherFileNeededFor(criterionName));
  }
  const otherNeedingWeatherFile = conditions.otherCriterionNeedingWeatherFile;
  if (otherNeedingWeatherFile != null && !conditions.hasWeatherFile) return plain(messages.weatherFileNeededFor(otherNeedingWeatherFile));
  const firstFieldWithError = Object.keys(form.fieldErrors)[0];
  if (firstFieldWithError !== undefined) {
    // A setting of another place is named with its place, so the user knows where to find it.
    const place = placeOfSetting(firstFieldWithError, conditions.criterionKeys) ?? conditions.shownIn;
    const label = shownLabelOf(firstFieldWithError, form.mode);
    if (place !== conditions.shownIn) return { reason: messages.fixSettingInStepToRun(label, placeTitleOf(place)), settingsElsewhere: place };
    return plain(criterionName === null ? messages.fixSettingToRun(label) : messages.fixSettingOfCriterionToRun(label, criterionName));
  }
  // A message that names no setting is shown above the settings of its place: "above" there, the place named elsewhere.
  const placesWithMessages = (Object.keys(conditions.stepErrorsByPlace) as SettingPlace[])
    .filter((place) => (conditions.stepErrorsByPlace[place] ?? []).length > 0);
  if (placesWithMessages.includes(conditions.shownIn)) return plain(criterionName === null ? messages.fixSettingsToRun : messages.fixSettingsOfCriterionToRun(criterionName));
  if (placesWithMessages.length > 0) return { reason: messages.fixSettingsInStepToRun(placeTitleOf(placesWithMessages[0])), settingsElsewhere: placesWithMessages[0] };
  // A warm-up that failed blocks nothing: a run then reports the problem itself (the service's warm-up says the same).
  if (conditions.warmUpState === null || conditions.warmUpState === "not_started" || conditions.warmUpState === "running") return plain(messages.runButtonWaitsForGpu);
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
 * The settings to fix of each place (UX 4.1, 11): the fields with an error of either form, counted in the place that draws them (the
 * six period settings are one field, as are the balance temperature and its dead band), and the messages that name no field,
 * counted where they are shown: the shared settings' in the project settings window, the criterion's in Criteria. The step rows
 * and the Settings button in the top bar read them.
 */
export function settingsToFixByPlace(shared: FormErrors, criterion: FormErrors, criterionKeys: ReadonlySet<string>): Partial<Record<SettingPlace, number>> {
  const fields = fieldsWithErrors({ ...shared.fieldErrors, ...criterion.fieldErrors });
  const counts: Partial<Record<SettingPlace, number>> = {};
  const count = (place: SettingPlace, added: number) => { if (added > 0) counts[place] = (counts[place] ?? 0) + added; };
  for (const name of fields) count(placeOfSetting(name, criterionKeys) ?? "project_settings", 1);
  count("project_settings", shared.stepErrors.length);
  count("criteria", criterion.stepErrors.length);
  return counts;
}

/**
 * The fields that hold an error, each counted once by the setting that draws it: the six period settings are one field, as are the
 * balance temperature and its dead band; the mode is one (its tiles). The places (settingsToFixByPlace) and a criterion's sections
 * (settingsToFixBySection) count these.
 */
export function fieldsWithErrors(fieldErrors: FormState["fieldErrors"]): Set<string> {
  return new Set(Object.keys(fieldErrors).map(fieldSettingOf));
}

/** All the settings to fix of a form: its fields with an error and its messages that name no field. */
export function settingsToFixCount(form: FormErrors): number {
  return fieldsWithErrors(form.fieldErrors).size + form.stepErrors.length;
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
  /**
   * The notice of a weather file added or replaced in this session; null when there is none to show; absent: the notice is not
   * shown here (the project settings, or a criterion's panel, which shows it over its folded settings, WeatherChangeRegion).
   */
  weatherChangeNotice?: WeatherChangeNoticeContent | null;
  /** The input roles the project has files for: Account for context blocking needs surroundings or terrain. */
  inputRoles?: readonly string[];
  /**
   * A setting whose inputs the project has no files for: left out ("hidden", a criterion's panel), or drawn greyed out with the
   * reason under it ("disabled", the project settings window, where a missing field of four would read as lost).
   */
  withoutInputs?: "hidden" | "disabled";
  /** Which settings to draw: the shared ones (the project settings) or a criterion's (its panel); absent, all. */
  settingShown?: (name: string) => boolean;
  /** The messages that name no setting to show here (those of the form these settings are saved by); absent, the form's. */
  stepErrors?: readonly string[];
  /** Whether the reason things are disabled is written here; false where another part says it (a criterion's Run analysis). */
  showsDisabledReason?: boolean;
}

const NO_INPUT_ROLES: readonly string[] = [];

/** The notice of a weather file in a live region on the page from the start, so that screen readers announce the notice that fills it. */
export function WeatherChangeRegion({ notice, form, onChange, disabled }: { notice: WeatherChangeNoticeContent | null; form: FormState;
                                     onChange: (values: Record<string, unknown>) => void; disabled: boolean }) {
  return (
    <div className="weather-change-region" role="status">
      {notice !== null && <WeatherChangeNotice {...notice} form={form} onChange={onChange} disabled={disabled} />}
    </div>
  );
}

/** The edge strip a weighted mode other than Night cooling reads with no field for it (a value left from Night cooling); null without one. */
function edgeStripOutsideItsField(form: FormState): number | null {
  const edgeStrip = form.userValues.edge_taper;
  const hasField = settingIsShownIn("edge_taper", form.mode);
  return !hasField && form.scoreKindByMode[form.mode] === "weighted_sum" && typeof edgeStrip === "number" && edgeStrip > 0 ? edgeStrip : null;
}

export function SettingsStep({ form, onChange, disabledReason, coldPeriod = null, hemisphere = "northern",
                               weatherChangeNotice, inputRoles = NO_INPUT_ROLES, withoutInputs = "hidden", settingShown, stepErrors = form.stepErrors,
                               showsDisabledReason = true }: SettingsStepProps) {
  const groups = settingsForStep("settings", form.mode, withoutInputs === "hidden" ? inputRoles : null, settingShown);
  const fieldExtras: Record<string, SettingFieldExtras> = { voxel_size: voxelSizeExtras(form), [ANALYSIS_PERIOD_FIELDS[0]]: { coldPeriod, hemisphere } };
  // Drawn without its inputs ("disabled"): greyed out, with the reason under it.
  for (const view of groups.flatMap((group) => [...group.essential, ...group.folded])) {
    if (!settingHasInputs(view.name, inputRoles)) fieldExtras[view.name] = { ...fieldExtras[view.name], disabled: true, notes: [messages.needsSurroundingsOrTerrain] };
  }
  const edgeStripCarriedOver = edgeStripOutsideItsField(form);
  return (
    <div className="settings-step">
      {disabledReason !== null && showsDisabledReason && <p className="step-reason">{disabledReason}</p>}
      {weatherChangeNotice !== undefined && (
        <WeatherChangeRegion notice={weatherChangeNotice} form={form} onChange={onChange} disabled={disabledReason !== null} />
      )}
      {stepErrors.map((error) => <p key={error} className="setting-error step-error"><WarningIcon /><span>{error}</span></p>)}
      {groups.map((group) => (
        <SettingGroup key={group.title} group={group} form={form} onChange={onChange} disabled={disabledReason !== null} fieldExtras={fieldExtras} />
      ))}
      {edgeStripCarriedOver !== null && (settingShown?.("edge_taper") ?? true) && <p className="step-reason">{messages.edgeStripCarriedOver(edgeStripCarriedOver)}</p>}
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
  /** Drawn as the lesser of two buttons side by side (the build next to Run analysis in Criteria). */
  secondary?: boolean;
  /** The id of a line that gives the reason for both of two buttons (CriteriaRunBar): the button names it and does not write its own. */
  sharedReasonId?: string;
  /** Drawn after the reason the button writes (Open settings, for a setting to fix in the project settings). */
  reasonAction?: ReactNode;
}

/** A step's run button, pinned under the step list, with the reason it is disabled and the progress of its run under it. */
export function RunAnalysisButton({ blocker, onRunAnalysis, label = messages.runAnalysis, feedback, secondary = false, sharedReasonId,
                                   reasonAction }: RunAnalysisButtonProps) {
  const ownReasonId = useId();
  const reasonId = sharedReasonId ?? ownReasonId;
  return (
    <div className="run-button-area">
      <button type="button" className={secondary ? "secondary-button" : "primary-button"} disabled={blocker !== null} aria-describedby={blocker !== null ? reasonId : undefined}
              onClick={onRunAnalysis}>
        {label}
      </button>
      {blocker !== null && sharedReasonId === undefined && <p id={reasonId} className="run-button-reason">{blocker}</p>}
      {blocker !== null && sharedReasonId === undefined && reasonAction}
      {feedback}
    </div>
  );
}
