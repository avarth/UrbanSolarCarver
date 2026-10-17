// Where each setting appears and how it reads (UX 5.4 to 5.7 and 7), from setting_presentation.json: the steps and their
// groups, the essential settings shown at once and the ones folded under "More <group> settings", and the percent display.
import { messages } from "../messages";
import presentationFile from "./setting_presentation.json";

export type StepName = "settings" | "carving" | "envelope_and_massing" | "export";
export type WidgetName = "analysis_period" | "threshold" | "tilted_plane_angles" | "sun_steps_per_hour" | "mesh_format" | "percent_slider";

/** One entry of setting_presentation.json. *modes* absent: every mode reads the setting. */
export interface SettingPresentation {
  label: string;
  unit: string;
  help: string;
  step: StepName;
  group: string;
  essential: "all" | string[] | false;
  modes?: string[];
  display?: "percent";
  widget?: WidgetName;
  label_for_modes?: Record<string, string>;
  unit_for_modes?: Record<string, string>;
  help_for_modes?: Record<string, string>;
}

/** A setting as the form draws it in one mode: the label, unit and help of that mode. */
export interface SettingView {
  name: string;
  label: string;
  unit: string;
  help: string;
  widget?: WidgetName;
  display?: "percent";
}

export interface SettingGroupView {
  title: string;
  essential: SettingView[];
  folded: SettingView[];
  foldLabel: string;
}

const PRESENTATION = presentationFile as { steps: Record<StepName, string[]>; settings: Record<string, SettingPresentation> };

export const SETTING_PRESENTATIONS: Readonly<Record<string, SettingPresentation>> = PRESENTATION.settings;

/** The six period settings, drawn as one widget under the name of the first. */
export const ANALYSIS_PERIOD_FIELDS = ["start_month", "start_day", "start_hour", "end_month", "end_day", "end_hour"] as const;

// Units that name the kind of control rather than a unit of the value; the control itself shows them.
const UNITS_NAMING_THE_CONTROL = new Set(["on/off", "choice", "dates, hours"]);
// A range given in the unit column: shown beside the value, but not a unit of a value ("default 2", not "default 2 0 to 6").
const RANGES_IN_THE_UNIT_COLUMN = new Set(["0 to 6"]);

export function settingIsReadBy(name: string, mode: string): boolean {
  const modes = SETTING_PRESENTATIONS[name]?.modes;
  return modes === undefined || modes.includes(mode);
}

function isEssentialIn(presentation: SettingPresentation, mode: string): boolean {
  return presentation.essential === "all" || (Array.isArray(presentation.essential) && presentation.essential.includes(mode));
}

export function settingView(name: string, mode: string): SettingView {
  const presentation = SETTING_PRESENTATIONS[name];
  return {
    name,
    label: presentation.label_for_modes?.[mode] ?? presentation.label,
    unit: presentation.unit_for_modes?.[mode] ?? presentation.unit,
    help: presentation.help_for_modes?.[mode] ?? presentation.help,
    widget: presentation.widget,
    display: presentation.display,
  };
}

/** The unit written beside the value, or "" when the unit only names the kind of control (on/off, choice). */
export function unitBesideValue(view: SettingView): string {
  return UNITS_NAMING_THE_CONTROL.has(view.unit) ? "" : view.unit;
}

/** The unit written after a value of the setting, as its default in the tooltip: neither a control kind nor a range. */
export function unitOfValue(view: SettingView): string {
  return RANGES_IN_THE_UNIT_COLUMN.has(view.unit) ? "" : unitBesideValue(view);
}

/**
 * The setting the form shows for a field the engine names: the name itself, or the name before a dot ("threshold.value",
 * "tilted_plane_angle_deg.float"); null when the form shows no such setting ("mode").
 */
export function presentedSettingOf(field: string): string | null {
  if (field in SETTING_PRESENTATIONS) return field;
  const settingName = field.split(".")[0];
  return settingName in SETTING_PRESENTATIONS ? settingName : null;
}

/** The fold under a group's essential settings; a group without essential settings is one fold titled with the group name. */
function foldLabelOf(title: string, essential: SettingView[]): string {
  if (essential.length === 0) return title;
  return messages.moreSettingsOfGroup[title as keyof typeof messages.moreSettingsOfGroup] ?? title;
}

/** The groups of *step* in *mode*, in the file's order, each with its essential and folded settings; empty groups are left out. */
export function settingsForStep(step: StepName, mode: string): SettingGroupView[] {
  const shownNames = Object.keys(SETTING_PRESENTATIONS).filter((name) =>
    SETTING_PRESENTATIONS[name].step === step && settingIsReadBy(name, mode)
    && !(ANALYSIS_PERIOD_FIELDS as readonly string[]).slice(1).includes(name));
  return PRESENTATION.steps[step].flatMap((title) => {
    const names = shownNames.filter((name) => SETTING_PRESENTATIONS[name].group === title);
    const essential = names.filter((name) => isEssentialIn(SETTING_PRESENTATIONS[name], mode)).map((name) => settingView(name, mode));
    const folded = names.filter((name) => !isEssentialIn(SETTING_PRESENTATIONS[name], mode)).map((name) => settingView(name, mode));
    if (essential.length === 0 && folded.length === 0) return [];
    return [{ title, essential, folded, foldLabel: foldLabelOf(title, essential) }];
  });
}

// 0.3 * 100 is 30.000000000000004 in floating point; twelve significant digits drop that noise and keep every real digit.
const withoutFloatingPointNoise = (value: number) => Number(value.toPrecision(12));

function isShownAsPercent(name: string): boolean {
  return SETTING_PRESENTATIONS[name]?.display === "percent";
}

/** The value as the form shows it: a percent setting stored as 0 to 1 is shown as 0 to 100. */
export function toDisplayValue(name: string, value: unknown): unknown {
  return isShownAsPercent(name) && typeof value === "number" ? withoutFloatingPointNoise(value * 100) : value;
}

/** The value as the engine stores it, from the one the form shows. */
export function fromDisplayValue(name: string, shown: unknown): unknown {
  return isShownAsPercent(name) && typeof shown === "number" ? withoutFloatingPointNoise(shown / 100) : shown;
}

/** The modes that label the threshold "Shadow tolerated" (time-based): there it is a cutoff in m²·h, asked for as a number. */
export function thresholdIsShadowToleratedIn(mode: string): boolean {
  return SETTING_PRESENTATIONS.threshold.label_for_modes?.[mode] !== undefined;
}
