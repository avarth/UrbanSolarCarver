// What the step summaries and marks read of an open project (step_summaries.ts), put together from the workspace's files, forms,
// stages, criteria and run summary.
import type { CriterionEntry, InputFileInfo, RunSummary } from "../api_client/client";
import { shownValue, type FormState } from "../settings_form/form_state";
import type { InputRole } from "../common/InputBox";
import { settingsToFixByPlace } from "../settings_form/SettingsStep";
import { type ProjectViewState } from "./step_summaries";
import { plainModeName } from "../modes";
import { messages } from "../messages";
import { type PipelineStage, type StageState } from "../stages";

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
  /** A project whose maximum volume is made from its sites: how many and their plan area; null otherwise. */
  sites?: { count: number; area: number } | null;
}

export function projectViewStateOf(inputs: ProjectViewInputs): ProjectViewState {
  const { files, form, summary, criteria } = inputs;
  const carvingSummaryOf = (entry: CriterionEntry) => summary?.criteria?.find((criterionSummary) => criterionSummary.id === entry.id);
  return {
    maxVolumeFiles: files.max_volume.length,
    sites: inputs.sites ?? null,
    hasWeatherFile: files.weather.length > 0,
    contextFiles: files.context.length,
    terrainFiles: files.terrain.length,
    mode: form.mode,
    northDegrees: inputs.northDegrees,
    voxelSize: Number(shownValue(form, "voxel_size")),
    settingsToFix: settingsToFixByPlace(inputs.sharedForm, inputs.criterionForm, inputs.criterionKeys),
    stages: inputs.stages,
    keptPercent: summary?.carving?.retention_pct ?? null,
    criterionOff: criteria.length === 1 && criteria[0].bypassed,
    criteriaInChain: criteria.length < 2 ? null
      : distinctNames(inputs.active).map((name, index) => ({ name, keptPercent: carvingSummaryOf(inputs.active[index])?.carving?.retention_pct ?? null })),
    totalFloorArea: summary?.massing?.total_floor_area_m2 ?? null,
    storeys: summary?.massing?.storeys_built ?? null,
  };
}

/**
 * The names the summary gives the criteria in the chain. A name the user did not give ends in its first test surface file ("Daylight
 * on windows"), so the summary says the mode alone, unless another criterion would read the same: then the whole name, and where
 * that is shared too, a number in chain order ("Sun hours on facades (2)").
 */
export function distinctNames(entries: readonly { name: string; named_by_user?: boolean; settings?: Record<string, unknown> | null }[]): string[] {
  const short = entries.map((entry) => (entry.named_by_user ? entry.name : plainModeName(String(entry.settings?.mode ?? entry.name))));
  const count = (names: string[], name: string) => names.filter((other) => other === name).length;
  const named = short.map((name, index) => (count(short, name) > 1 && !entries[index].named_by_user ? entries[index].name : name));
  const seen = new Map<string, number>();
  return named.map((name) => {
    if (count(named, name) < 2) return name;
    const number = (seen.get(name) ?? 0) + 1;
    seen.set(name, number);
    return messages.numberedName(name, number);
  });
}
