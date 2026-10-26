// The Site and grid step (spec 7.1): the analysis settings every criterion shares, those that are not criterion keys (GET
// criterion-keys): north, the surroundings switch, the voxel size with the grid budget line under it, and the detail settings.
// Run analysis is pinned under the steps while it is open (ProjectWorkspace).
import type { FormState } from "../settings_form/form_state";
import { SettingsStep } from "./SettingsStep";

interface SiteAndGridStepProps {
  form: FormState;
  /** The messages of the shared settings' last save that name no setting. */
  stepErrors: readonly string[];
  criterionKeys: ReadonlySet<string>;
  onChange: (values: Record<string, unknown>) => void;
  /** Why the settings cannot be changed now (a run is in progress); null when they can. */
  disabledReason: string | null;
  /** The input roles the project has files for: Account for context blocking shows only with surroundings or terrain. */
  inputRoles?: readonly string[];
}

export function SiteAndGridStep({ form, stepErrors, criterionKeys, onChange, disabledReason, inputRoles }: SiteAndGridStepProps) {
  return (
    <SettingsStep form={form} stepErrors={stepErrors} onChange={onChange} disabledReason={disabledReason} inputRoles={inputRoles}
                  settingShown={(name) => !criterionKeys.has(name)} />
  );
}
