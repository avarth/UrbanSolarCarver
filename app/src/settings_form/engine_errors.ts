// The engine's config errors in the interface's words (UX 11). The engine writes its messages for the YAML and the command
// line: config names ("grid_step"), and for an error of the whole config (a model validator) no field and Pydantic's
// "Value error, " in front. Here such an error goes under every setting it names, so their fields are outlined and their
// folds open; the known ones are said in the interface's own sentences, and any other has the labels in place of the names.
import { messages } from "../messages";
import { formattedNumber, withUnit } from "../steps/format_numbers";
import { plainModeName } from "../steps/step_summaries";
import { ANALYSIS_PERIOD_FIELDS, presentedSettingOf, SETTING_PRESENTATIONS, settingView } from "./presentation";

/** An engine error as the form shows it: under each of *settings*, or for the step when it names none. */
export interface ShownConfigError {
  settings: string[];
  message: string;
}

const VALUE_ERROR_PREFIX = /^Value error, /;
// A config name in an engine message: a lower-case word with underscores ("grid_step"), maybe followed by "=value".
const CONFIG_NAME = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;
const QUOTED_MODE = /\bmode '([a-z_-]+)'/g;
const SAMPLING_ABOVE_VOXEL_SIZE = /grid_step \(([\d.]+) m\) must be ≤ voxel_size \(([\d.]+) m\)/;
const DAY_NOT_IN_MONTH = /\b(start|end)_day=(\d+) is invalid for month (\d+) \(max (\d+) days\)/;
const PERIOD_MISSING = /\bmode '([a-z_-]+)' requires analysis period fields/;
const WEATHER_FILE_MISSING = /\brequires epw_path\b/;

const capitalised = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** The name the interface gives a setting in *mode*: its label, or for one of the six period settings its own field name. */
function shownNameOf(setting: string, mode: string): string {
  if (Object.hasOwn(messages.periodFieldNames, setting)) return messages.periodFieldNames[setting as keyof typeof messages.periodFieldNames];
  return settingView(setting, mode).label;
}

/** The settings the form shows that *message* names, in the order it names them. */
function settingsNamedIn(message: string): string[] {
  const named = (message.match(CONFIG_NAME) ?? []).filter((name) => Object.hasOwn(SETTING_PRESENTATIONS, name));
  return [...new Set(named)];
}

/** *message* with the labels of *mode* in place of config names and plain mode names in place of engine ones. */
function inInterfaceWords(message: string, mode: string, asSentence = true): string {
  const named = message.replace(VALUE_ERROR_PREFIX, "")
    .replace(QUOTED_MODE, (_whole, engineName: string) => plainModeName(engineName))
    .replace(CONFIG_NAME, (name) => (Object.hasOwn(SETTING_PRESENTATIONS, name) ? shownNameOf(name, mode).toLowerCase() : name));
  return asSentence ? capitalised(named) : named;
}

/** The messages the engine writes for the whole config that the interface says in its own sentence. */
function knownConfigError(message: string, mode: string): ShownConfigError | null {
  const label = (setting: string) => settingView(setting, mode).label;
  const sampling = SAMPLING_ABOVE_VOXEL_SIZE.exec(message);
  if (sampling !== null) {
    return { settings: ["grid_step", "voxel_size"],
             message: messages.samplingAboveVoxelSize(label("grid_step"), withUnit(formattedNumber(Number(sampling[1])), "m"),
                                                      label("voxel_size"), withUnit(formattedNumber(Number(sampling[2])), "m")) };
  }
  const day = DAY_NOT_IN_MONTH.exec(message);
  if (day !== null) {
    const setting = `${day[1]}_day`;
    return { settings: [setting],
             message: messages.dayNotInMonth(shownNameOf(setting, mode), Number(day[2]), messages.monthNames[Number(day[3]) - 1], Number(day[4])) };
  }
  const period = PERIOD_MISSING.exec(message);
  if (period !== null) return { settings: [ANALYSIS_PERIOD_FIELDS[0]], message: messages.periodIncomplete(plainModeName(period[1])) };
  if (WEATHER_FILE_MISSING.test(message)) return { settings: [], message: messages.weatherFileNeeded };
  return null;
}

/**
 * Where the form shows an engine error of a save or a run in *mode*, and in which words. An error of a setting the mode does
 * not show (an error of a run, of a stored config.yaml) goes to the step with the setting's label, so it is never hidden.
 */
export function shownConfigErrorOf(field: string | null, message: string, mode: string): ShownConfigError {
  if (field === null) {
    const known = knownConfigError(message, mode);
    if (known !== null) return known;
    return { settings: settingsNamedIn(message), message: inInterfaceWords(message, mode) };
  }
  // The engine names a part of a setting after a dot ("threshold.value"); the error goes under the setting the form shows.
  const setting = presentedSettingOf(field);
  if (field === "epw_path") return { settings: [], message: messages.weatherFileNeeded };
  // A setting the form has no field for: the mode by the name of its step, any other by the engine's name for it.
  if (setting === null) {
    return { settings: [], message: messages.settingProblem(field === "mode" ? messages.stepTitles.mode : field, inInterfaceWords(message, mode, false)) };
  }
  return { settings: [setting], message: inInterfaceWords(message, mode) };
}

/** An error on a setting the mode does not show, said for the step with the setting's name (once, when it already names it). */
export function errorOfHiddenSetting(setting: string, message: string, mode: string): string {
  const name = shownNameOf(setting, mode);
  return message.toLowerCase().startsWith(name.toLowerCase()) ? message : messages.settingProblem(name, message);
}
