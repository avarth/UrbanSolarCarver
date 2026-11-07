// The two settings forms of an open project: the shared settings, shown in Site and grid, and the selected criterion's, shown in its
// panel. The steps read them as one (useBothForms); each save goes to where its settings are kept.
import { useState } from "react";
import { putSharedSettings, updateCriterion, type ModeInfo, type ProjectDetail } from "../api_client/client";
import type { CriteriaHook } from "../criteria/use_criteria";
import { sharedRefusalShown, splitSettings, useBothForms } from "../settings_form/two_forms";
import { useSettingsForm, type FormStart, type SettingsSend } from "../settings_form/form_state";

interface ProjectFormsContext {
  token: string;
  project: ProjectDetail;
  schema: FormStart["schema"];
  modes: ModeInfo[];
  criterionKeys: ReadonlySet<string>;
  criteria: CriteriaHook;
  /** The criterion whose settings the criterion form holds. */
  formCriterionId: string;
}

export function useProjectForms({ token, project, schema, modes, criterionKeys, criteria, formCriterionId }: ProjectFormsContext) {
  // The project's settings are the shared ones with the first criterion's: each form starts from its own. The shared form takes
  // the criterion's mode, which decides the settings it shows, but does not save it. The forms read their start once, when made.
  const [formStarts] = useState((): { shared: FormStart; criterion: FormStart } => {
    const { shared, criterion } = splitSettings(project.settings, criterionKeys);
    return {
      shared: { schema, modes, settings: { ...shared, mode: criterion.mode }, gridPlan: project.grid_plan, savesMode: false },
      criterion: { schema, modes, settings: criterion, gridPlan: null },
    };
  });
  // A criterion's save replaces its settings; a new mode may rename it, so its entry is kept. The save goes to the criterion whose
  // settings the form holds (the form reads this send when a save goes out).
  const saveCriterionSettings: SettingsSend = async (formToken, projectName, values) => {
    const entry = await updateCriterion(formToken, projectName, formCriterionId, { values });
    criteria.applyReply(entry);
    return entry;
  };
  // A shared value refused by a criterion's own setting is said in Site and grid, with that criterion's name (sharedRefusalShown).
  const saveSharedSettings: SettingsSend = (formToken, projectName, values) => putSharedSettings(formToken, projectName, values).catch((error: unknown) => {
    const now = criteria.current().criteria;
    throw sharedRefusalShown(error, criterionKeys, (id) => now.find((entry) => entry.id === id) ?? null, now.length >= 2);
  });
  const sharedForm = useSettingsForm(token, project.name, formStarts.shared, saveSharedSettings);
  const criterionForm = useSettingsForm(token, project.name, formStarts.criterion, saveCriterionSettings);
  return { sharedForm, criterionForm, ...useBothForms(sharedForm, criterionForm, criterionKeys) };
}
