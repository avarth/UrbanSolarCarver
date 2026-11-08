// The names of the four steps of Design and of the four pipeline stages, and the states a stage and a step row can be in.

/** The steps (spec 7.1): the site's inputs, the criteria, then the envelope and massing and the downloads. */
export type StepName = "inputs" | "criteria" | "envelope_and_massing" | "export";
/** Where a setting is changed: a step, or the project settings window (the settings every criterion shares, opened from the top bar). */
export type SettingPlace = StepName | "project_settings";
export type PipelineStage = "preprocessing" | "thresholding" | "exporting" | "massing";
export type StageState = "current" | "out_of_date" | "missing";
export type StepMark = "done" | "error" | "none";

/** The steps in the order of the accordion. */
export const STEP_NAMES: readonly StepName[] = ["inputs", "criteria", "envelope_and_massing", "export"];
