// The Settings step (UX 5.4, 11): the settings the analysis reads in their groups, the grid under Voxel size, the grid-over-budget
// message in place of the engine's, and messages that name no single setting. The step's Run analysis button sits pinned at the
// bottom of the panel (RunAnalysisButton), disabled with the first reason that blocks the run.
import { useId } from "react";
import type { HealthReply } from "../api_client/client";
import { messages } from "../messages";
import type { FormState } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS, settingsForStep, settingView } from "../settings_form/presentation";
import { WarningIcon, type SettingFieldExtras } from "../settings_form/SettingField";
import { SettingGroup } from "../settings_form/SettingGroup";
import { gridIsOverBudget, smallestVoxelSizeWithinBudget } from "./grid_budget";
import "./steps.css";

export interface RunAnalysisConditions {
  runActive: boolean;
  maxVolumeFiles: number;
  testSurfaceFiles: number;
  modeNeedsWeatherFile: boolean;
  hasWeatherFile: boolean;
  form: Pick<FormState, "mode" | "fieldErrors" | "stepErrors">;
  warmUpState: HealthReply["warm_up"]["state"] | null;
}

/** The label of a setting as the form shows it; the six period settings are one field, "Analysis period". */
function shownLabelOf(settingName: string, mode: string): string {
  const shownName = (ANALYSIS_PERIOD_FIELDS as readonly string[]).includes(settingName) ? ANALYSIS_PERIOD_FIELDS[0] : settingName;
  return settingView(shownName, mode).label;
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
  if (firstFieldWithError !== undefined) return messages.fixSettingToRun(shownLabelOf(firstFieldWithError, form.mode));
  if (form.stepErrors.length > 0) return messages.fixSettingsToRun;
  // A warm-up that failed blocks nothing: a run then reports the problem itself (the service's warm-up says the same).
  if (conditions.warmUpState === null || conditions.warmUpState === "not_started" || conditions.warmUpState === "running") return messages.runButtonWaitsForGpu;
  return null;
}

/** Field errors and step errors together: the count of the step's "settings to fix". */
export function settingsToFixCount(form: Pick<FormState, "fieldErrors" | "stepErrors">): number {
  return Object.keys(form.fieldErrors).length + form.stepErrors.length;
}

/** The grid line under Voxel size, or the over-budget message in its place. */
function voxelSizeExtras(form: FormState): SettingFieldExtras {
  const plan = form.gridPlan;
  if (plan === null) return {};
  if (!gridIsOverBudget(plan)) return { note: messages.gridSize(plan.resolution, plan.total_voxels) };
  const text = messages.gridOverBudget(plan.resolution, plan.total_voxels, plan.budget_voxels,
    smallestVoxelSizeWithinBudget(plan.voxel_size, plan.total_voxels, plan.budget_voxels));
  return { errorContent: <>{text.description} <strong>{text.advice}</strong></> };
}

interface SettingsStepProps {
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  /** Why the settings cannot be changed now (a run is in progress: the service refuses to save); null when they can. */
  disabledReason: string | null;
}

export function SettingsStep({ form, onChange, disabledReason }: SettingsStepProps) {
  const fieldExtras = { voxel_size: voxelSizeExtras(form) };
  return (
    <div className="settings-step">
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
      {form.stepErrors.map((error) => <p key={error} className="setting-error step-error"><WarningIcon /><span>{error}</span></p>)}
      {settingsForStep("settings", form.mode).map((group) => (
        <SettingGroup key={group.title} group={group} form={form} onChange={onChange} disabled={disabledReason !== null} fieldExtras={fieldExtras} />
      ))}
    </div>
  );
}

interface RunAnalysisButtonProps {
  blocker: string | null;
  onRunAnalysis: () => void;
}

/** Run analysis, pinned under the step list, with the reason it is disabled under it. */
export function RunAnalysisButton({ blocker, onRunAnalysis }: RunAnalysisButtonProps) {
  const reasonId = useId();
  return (
    <div className="run-button-area">
      <button type="button" className="primary-button" disabled={blocker !== null} aria-describedby={blocker !== null ? reasonId : undefined}
              onClick={onRunAnalysis}>
        {messages.runAnalysis}
      </button>
      {blocker !== null && <p id={reasonId} className="run-button-reason">{blocker}</p>}
    </div>
  );
}
