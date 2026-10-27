// What the step summaries and marks read of an open project (step_summaries.ts), put together from the workspace's files, forms,
// stages, criteria and run summary.
import type { CriterionEntry, InputFileInfo, RunSummary } from "../api_client/client";
import { shownValue, type FormState } from "../settings_form/form_state";
import type { InputRole } from "./InputsStep";
import { settingsToFixByStep } from "./SettingsStep";
import { plainModeName, type PipelineStage, type ProjectViewState, type StageState } from "./step_summaries";

export interface ProjectViewInputs {
  files: Record<InputRole, InputFileInfo[]>;
  /** The two forms as one (useBothForms), and each form on its own for the settings to fix. */
  form: FormState;
  sharedForm: FormState;
  criterionForm: FormState;
  criterionKeys: ReadonlySet<string>;
  northDegrees: number;
  /** The stages as the steps show them (useStageStatus). */
  stages: Record<PipelineStage, StageState>;
  /** The run summary of the selected criterion's results; null before a run. */
  summary: RunSummary | null;
  criteria: CriterionEntry[];
  /** The criteria that are on, in carving order. */
  active: CriterionEntry[];
}

export function projectViewStateOf(inputs: ProjectViewInputs): ProjectViewState {
  const { files, form, summary, criteria } = inputs;
  const carvingSummaryOf = (entry: CriterionEntry) => summary?.criteria?.find((criterionSummary) => criterionSummary.id === entry.id);
  return {
    maxVolumeFiles: files.max_volume.length,
    hasWeatherFile: files.weather.length > 0,
    contextFiles: files.context.length,
    terrainFiles: files.terrain.length,
    mode: form.mode,
    northDegrees: inputs.northDegrees,
    voxelSize: Number(shownValue(form, "voxel_size")),
    settingsToFix: settingsToFixByStep(inputs.sharedForm, inputs.criterionForm, inputs.criterionKeys),
    stages: inputs.stages,
    keptPercent: summary?.carving?.retention_pct ?? null,
    criterionOff: criteria.length === 1 && criteria[0].bypassed,
    // A name the user did not give ends in its first test surface file ("Daylight on windows"); the summary says the mode alone.
    criteriaInChain: criteria.length < 2 ? null
      : inputs.active.map((entry) => ({ name: entry.named_by_user ? entry.name : plainModeName(String(entry.settings?.mode ?? entry.name)),
                                        keptPercent: carvingSummaryOf(entry)?.carving?.retention_pct ?? null })),
    totalFloorArea: summary?.massing?.total_floor_area_m2 ?? null,
    storeys: summary?.massing?.storeys_built ?? null,
  };
}
