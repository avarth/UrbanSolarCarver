// Where each setting appears and how it reads (UX 5.4 to 5.7 and 7), from setting_presentation.json: the steps and their
// groups, the essential settings shown at once and the ones folded under "More <group> settings", the displays in other units than
// the engine's (a share in percent, a count of voxels in m³), and the slider of each ranged setting (R2 4.1).
import { messages } from "../messages";
import presentationFile from "./setting_presentation.json";

/**
 * The parts of the form a setting belongs to (setting_presentation.json): "settings" (the analysis: Site and grid shows its shared
 * settings, a criterion's panel its own), "carving" (a criterion's carving rule), and the Envelope and massing and Export steps.
 */
export type StepName = "settings" | "carving" | "envelope_and_massing" | "export";
export type WidgetName = "analysis_period" | "threshold" | "tilted_plane_angles" | "sun_steps_per_hour" | "mesh_format" | "balance_temperature";

/**
 * The slider of a ranged setting (R2 4.1), in the engine's units: the range people normally use, inside the engine's limits
 * (the packaging test checks it against the schema). The number field beside it takes any value the engine accepts.
 */
export interface SliderRange {
  low: number;
  high: number;
  step: number;
}

/**
 * How the form shows a value the engine stores in another unit: "percent", a share stored as 0 to 1, as 0 to 100; "voxel_volume",
 * a count of voxels, as their volume in m³ at the voxel size the form shows.
 */
export type DisplayConversion = "percent" | "voxel_volume";

/**
 * One entry of setting_presentation.json. *modes*: the modes whose form shows the setting; absent, every mode's.
 * *shown_with_inputs*: the input roles of which the project must have files for the form to show it (any of them); absent, always.
 */
export interface SettingPresentation {
  label: string;
  unit: string;
  help: string;
  step: StepName;
  group: string;
  essential: "all" | string[] | false;
  modes?: string[];
  shown_with_inputs?: string[];
  display?: DisplayConversion;
  widget?: WidgetName;
  slider?: SliderRange;
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
  display?: DisplayConversion;
  slider?: SliderRange;
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

/** The balance temperature and its dead band, drawn as one slider with two handles under the name of the first (R2 4.2). */
export const BALANCE_TEMPERATURE_FIELDS = ["balance_temperature", "balance_offset"] as const;

const SETTINGS_DRAWN_AS_ONE_FIELD: readonly (readonly string[])[] = [ANALYSIS_PERIOD_FIELDS, BALANCE_TEMPERATURE_FIELDS];

/** The setting whose field draws *name*: the first of the settings drawn as one field ("end_hour" is in "start_month"), else *name*. */
export function fieldSettingOf(name: string): string {
  return SETTINGS_DRAWN_AS_ONE_FIELD.find((names) => names.includes(name))?.[0] ?? name;
}

/** The settings the field of *name* draws: every one of the settings drawn as one field, else *name* alone. */
export function settingsOfField(name: string): readonly string[] {
  return SETTINGS_DRAWN_AS_ONE_FIELD.find((names) => names[0] === name) ?? [name];
}

// Units that name the kind of control rather than a unit of the value; the control itself shows them.
const UNITS_NAMING_THE_CONTROL = new Set(["on/off", "choice", "dates, hours"]);

export function settingIsShownIn(name: string, mode: string): boolean {
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
    slider: presentation.slider,
  };
}

/** The unit written beside the value, or "" when the unit only names the kind of control (on/off, choice). */
export function unitBesideValue(view: SettingView): string {
  return UNITS_NAMING_THE_CONTROL.has(view.unit) ? "" : view.unit;
}


/**
 * The setting the form shows for a field the engine names: the name itself, or the name before a dot ("threshold.value",
 * "tilted_plane_angle_deg.float"); null when the form shows no such setting ("mode").
 */
export function presentedSettingOf(field: string): string | null {
  // Own keys only: "constructor" or "toString" are in every object through its prototype, and are no setting.
  if (Object.hasOwn(SETTING_PRESENTATIONS, field)) return field;
  const settingName = field.split(".")[0];
  return Object.hasOwn(SETTING_PRESENTATIONS, settingName) ? settingName : null;
}

/**
 * The fold under a group's essential settings; a group without essential settings is one fold titled with the group name, or a
 * title that says it holds settings when the name alone would read as a heading ("Detail settings").
 */
function foldLabelOf(title: string, essential: SettingView[]): string {
  if (essential.length === 0) return messages.foldedGroupTitles[title as keyof typeof messages.foldedGroupTitles] ?? title;
  return messages.moreSettingsOfGroup[title as keyof typeof messages.moreSettingsOfGroup] ?? title;
}

/** Whether a project with files in *inputRoles* has the inputs a setting needs (shown_with_inputs). */
function hasInputsFor(name: string, inputRoles: readonly string[]): boolean {
  const needed = SETTING_PRESENTATIONS[name]?.shown_with_inputs;
  return needed === undefined || needed.some((role) => inputRoles.includes(role));
}

/**
 * The groups of *step* in *mode*, in the file's order, each with its essential and folded settings; empty groups are left out.
 * *inputRoles*: the input roles the project has files for; a setting that needs inputs (shown_with_inputs) shows only with them.
 * *settingShown*: which settings of the step to draw (the shared ones in Site and grid, a criterion's in its panel); absent, all.
 */
export function settingsForStep(step: StepName, mode: string, inputRoles: readonly string[] = [],
                                settingShown: (name: string) => boolean = () => true): SettingGroupView[] {
  const shownNames = Object.keys(SETTING_PRESENTATIONS).filter((name) =>
    SETTING_PRESENTATIONS[name].step === step && settingIsShownIn(name, mode) && hasInputsFor(name, inputRoles) && fieldSettingOf(name) === name
    && settingShown(name));
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

/** The volume of one voxel in m³ at *voxelSize* (the form's value of voxel_size), or null when it is not a size. */
function voxelVolume(voxelSize: unknown): number | null {
  return typeof voxelSize === "number" && voxelSize > 0 ? voxelSize ** 3 : null;
}

/**
 * The value as the form shows it: a share stored as 0 to 1 as 0 to 100, a count of voxels as their volume in m³ at *voxelSize*
 * (the voxel size the form shows).
 */
export function toDisplayValue(name: string, value: unknown, voxelSize: unknown = null): unknown {
  if (typeof value !== "number") return value;
  const display = SETTING_PRESENTATIONS[name]?.display;
  if (display === "percent") return withoutFloatingPointNoise(value * 100);
  const volume = display === "voxel_volume" ? voxelVolume(voxelSize) : null;
  return volume === null ? value : withoutFloatingPointNoise(value * volume);
}

/** The value as the engine stores it, from the one the form shows: a volume becomes a whole number of voxels, at least one. */
export function fromDisplayValue(name: string, shown: unknown, voxelSize: unknown = null): unknown {
  if (typeof shown !== "number") return shown;
  const display = SETTING_PRESENTATIONS[name]?.display;
  if (display === "percent") return withoutFloatingPointNoise(shown / 100);
  const volume = display === "voxel_volume" ? voxelVolume(voxelSize) : null;
  return volume === null ? shown : Math.max(1, Math.round(shown / volume));
}

/** The slider of *view* in the units the form shows (0 to 100 for a share stored as 0 to 1); undefined for a setting without one. */
export function shownSliderOf(view: SettingView): SliderRange | undefined {
  if (view.slider === undefined) return undefined;
  const shown = (value: number) => toDisplayValue(view.name, value) as number;
  return { low: shown(view.slider.low), high: shown(view.slider.high), step: shown(view.slider.step) };
}

/** The modes that label the threshold "Shadow tolerated" (time-based): there it is a cutoff in m²·h, asked for as a number. */
export function thresholdIsShadowToleratedIn(mode: string): boolean {
  return SETTING_PRESENTATIONS.threshold.label_for_modes?.[mode] !== undefined;
}
