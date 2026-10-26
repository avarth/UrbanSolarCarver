// The folded sections of a criterion's panel (CriterionPanel): which section holds a setting, the one line each says while it is
// closed, and the settings to fix in each. Test surfaces and Carving rule start open, Mode and Settings closed.
import { messages } from "../messages";
import { periodFromSettings, periodInWords, type AnalysisPeriodField } from "../settings_form/analysis_period";
import { defaultValue, shownValue, type FormState } from "../settings_form/form_state";
import { ANALYSIS_PERIOD_FIELDS, fieldSettingOf, presentedSettingOf, SETTING_PRESENTATIONS, settingIsShownIn, unitBesideValue } from "../settings_form/presentation";
import type { ThresholdSpec } from "../settings_form/widgets/ThresholdRule";
import { carvingRuleOf, manualCarveAmountOf, thresholdControlOf } from "../steps/CarvingStep";
import { formattedNumber, withUnit } from "../steps/format_numbers";
import { plainModeName } from "../steps/step_summaries";

export type PanelSectionId = "test_surfaces" | "mode" | "settings" | "carving";

/** The sections in the order of the panel. */
export const PANEL_SECTIONS: readonly PanelSectionId[] = ["test_surfaces", "mode", "settings", "carving"];

export const DEFAULT_OPEN_SECTIONS: ReadonlySet<PanelSectionId> = new Set(["test_surfaces", "carving"]);

const sameValue = (first: unknown, second: unknown) => JSON.stringify(first) === JSON.stringify(second);

/** The section whose field shows a setting: Mode for the mode, Carving rule for a carving setting, Settings for the others. */
export function sectionOfSetting(name: string): PanelSectionId {
  if (name === "mode") return "mode";
  const presented = presentedSettingOf(name);
  return presented !== null && SETTING_PRESENTATIONS[presented].step === "carving" ? "carving" : "settings";
}

/** "windows.ply"; "a.ply, b.ply"; "3 files"; "None yet". */
export function testSurfacesSummary(files: string[]): string {
  if (files.length === 0) return messages.noTestSurfacesYet;
  if (files.length === 1) return files[0];
  if (files.length === 2) return messages.twoFileNames(files[0], files[1]);
  return messages.fileCount(files.length);
}

export function modeSummary(mode: string): string {
  return plainModeName(mode);
}

/**
 * A mode that reads an analysis period: the period in words, "21 Dec, 7 to 19 h". Another mode: "Starting values" while none of
 * the criterion's settings in Settings differs from the mode's starting values, else "2 settings changed".
 */
export function criterionSettingsSummary(form: FormState, criterionKeys: ReadonlySet<string>): string {
  if (settingIsShownIn(ANALYSIS_PERIOD_FIELDS[0], form.mode)) {
    const settings = Object.fromEntries(ANALYSIS_PERIOD_FIELDS.map((name) => [name, shownValue(form, name)])) as Record<AnalysisPeriodField, number | null>;
    const period = periodFromSettings(settings);
    if (period !== null) return periodInWords(period);
  }
  const changedFields = new Set(Object.entries(form.userValues)
    .filter(([name, value]) => criterionKeys.has(name) && SETTING_PRESENTATIONS[name]?.step === "settings" && settingIsShownIn(name, form.mode)
      && !sameValue(value, defaultValue(form, name)))
    .map(([name]) => fieldSettingOf(name)));
  return changedFields.size === 0 ? messages.startingValues : messages.settingsChanged(changedFields.size);
}

/** "Carve 70 %" (Manual), "Cutoff 1.5 m²·h" (a fixed cutoff), "Automatic", or the angle rule's line. */
export function carvingRuleSummary(form: FormState): string {
  const control = thresholdControlOf(form.mode);
  if (control === null) return messages.angleRuleSummary;
  const spec = shownValue(form, "threshold") as ThresholdSpec | null;
  if (control.name === "threshold" || spec?.method === "cutoff") {
    // Shadow tolerated unset is a cutoff at 0, as the engine applies it.
    const cutoff = spec?.method === "cutoff" && typeof spec.value === "number" ? spec.value : 0;
    return messages.cutoffSummary(withUnit(formattedNumber(cutoff), control.name === "threshold" ? unitBesideValue(control) : ""));
  }
  if (carvingRuleOf(form) === "headtail") return messages.carvingRuleChoices.headtail;
  const carveAmount = manualCarveAmountOf(form, null);
  return carveAmount === null ? messages.carvingRuleChoices.carve_fraction
    : messages.carveAmountSummary(withUnit(formattedNumber(carveAmount * 100), messages.units.percent));
}

/**
 * The settings to fix in each section: the criterion's fields with an error of its last save (the six period settings are one
 * field, as are the balance temperature and its dead band), and the messages that name no setting, which Settings shows.
 */
export function settingsToFixBySection(form: { fieldErrors: FormState["fieldErrors"]; stepErrors: readonly string[] }, criterionKeys: ReadonlySet<string>)
  : Partial<Record<PanelSectionId, number>> {
  const counts: Partial<Record<PanelSectionId, number>> = {};
  const count = (section: PanelSectionId, added: number) => { if (added > 0) counts[section] = (counts[section] ?? 0) + added; };
  const fields = new Set(Object.keys(form.fieldErrors)
    .map((name) => (name === "mode" ? name : fieldSettingOf(presentedSettingOf(name) ?? name)))
    .filter((name) => criterionKeys.has(name)));
  for (const name of fields) count(sectionOfSetting(name), 1);
  count("settings", form.stepErrors.length);
  return counts;
}
