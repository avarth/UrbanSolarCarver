// A criterion's carving rule (UX 5.5, 11; once the Carving step, now in the criterion's panel, CriterionPanel): in the weighted
// modes the carving rule at the top (Manual or Automatic), then the control of the
// rule (Shadow tolerated in m²·h for Solar time-based, Carve amount in % under Manual, a line for Automatic; the angle rule's
// message), the "Update when I change the threshold" switch, remembered per project, the histogram with its cutoff line, the
// numbers of the last carving, and the other carving settings folded last.
// With the switch on, letting go of the slider, of the line on the histogram or leaving the number field reruns the carving, as
// does a change of another carving setting (a switch or a choice at once, a number field when the user leaves it, a slider when it
// is let go); off, Update carving does.
// The line on the histogram can be dragged in every rule: it previews the share of the volume a cutoff keeps, worked out from the
// score points, and sets the carve amount that cutoff stands for (Manual; Automatic turns into Manual, which the step says), or
// the cutoff itself (Shadow tolerated). A cutoff a weighted mode's config holds (from the command line or an earlier version) is
// shown as Manual, at the carve amount it stands for.
// When the analysis is out of date the histogram and numbers of the last carving are shown dimmed, its controls disabled, with a
// line that says so (Run analysis is in the bar pinned under the Criteria step).
import { useEffect, useId, useMemo, useRef, useState, type FocusEvent, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import type { RunSummary } from "../api_client/client";
import { messages } from "../messages";
import { shownValue, type FormState } from "../settings_form/form_state";
import { fromDisplayValue, settingsForStep, settingView, thresholdIsShadowToleratedIn, toDisplayValue, type SettingView } from "../settings_form/presentation";
import { defaultTextOf, fieldErrorOf, WarningIcon } from "../settings_form/SettingField";
import { SettingGroup } from "../settings_form/SettingGroup";
import { SettingTooltip } from "../settings_form/SettingTooltip";
import { NumberInput } from "../settings_form/widgets/NumberInput";
import type { ThresholdSpec } from "../settings_form/widgets/ThresholdRule";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { carveAmountAt, cutoffForCarveAmount, cutoffStep, keptShareAt, rankScorePoints, roundedToStep, type RankedScorePoints } from "./cutoff_preview";
import { formatNumber, formatPercent, formattedNumber, withUnit } from "./format_numbers";
import { ScoreHistogram } from "./ScoreHistogram";
import "./steps.css";

type CarvingSummary = NonNullable<RunSummary["carving"]>;
/** The carving rule of a weighted mode: Manual (a carve amount) or Automatic (head/tail breaks). */
type CarvingRule = "carve_fraction" | "headtail";

const AUTO_UPDATE_STORAGE_PREFIX = "usc.autoUpdate.";
const CARVING_GROUP = "How much to carve";
const CARVING_RULES: readonly CarvingRule[] = ["carve_fraction", "headtail"];
// The settings that decide the cutoff: the rule (and its value) and the carve amount.
const THRESHOLD_SETTINGS = ["threshold", "carve_fraction"] as const;
// A carve amount set from the line on the histogram is rounded to a tenth of a percent.
const CARVE_AMOUNT_STEP = 0.001;
// Keys that move a range input; letting go of one is letting go of the slider.
const SLIDER_KEYS = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"]);

export function autoUpdateStorageKey(project: string): string {
  return `${AUTO_UPDATE_STORAGE_PREFIX}${project}`;
}

/** Whether the project's carving reruns on a threshold change: on unless the user switched it off on this computer. */
export function readAutoUpdate(project: string): boolean {
  try {
    return window.localStorage.getItem(autoUpdateStorageKey(project)) !== "off";
  } catch {
    return true;
  }
}

/**
 * Carries the auto-update choice of a project to its new name (*to*), or drops it (*to* null) for a project deleted or reset
 * to its example. Without storage there is nothing to carry.
 */
export function moveAutoUpdateChoice(from: string, to: string | null): void {
  try {
    const choice = window.localStorage.getItem(autoUpdateStorageKey(from));
    window.localStorage.removeItem(autoUpdateStorageKey(from));
    if (to !== null && choice !== null) window.localStorage.setItem(autoUpdateStorageKey(to), choice);
  } catch {
    // storage is blocked: no choice was kept
  }
}

export function useAutoUpdate(project: string): [boolean, (on: boolean) => void] {
  const [autoUpdate, setAutoUpdate] = useState(() => readAutoUpdate(project));
  const remember = (on: boolean) => {
    setAutoUpdate(on);
    try {
      window.localStorage.setItem(autoUpdateStorageKey(project), on ? "on" : "off");
    } catch {
      // storage is blocked: the choice holds for this page load
    }
  };
  return [autoUpdate, remember];
}

/** The setting the threshold control sets in *mode*: Shadow tolerated (threshold), Carve amount (carve_fraction), or none. */
export function thresholdControlOf(mode: string): SettingView | null {
  return settingsForStep("carving", mode).find((group) => group.title === CARVING_GROUP)?.essential[0] ?? null;
}

/**
 * The carving rule the form holds in a weighted mode: Automatic for head/tail breaks, else Manual, which is also how a cutoff the
 * config holds is shown.
 */
export function carvingRuleOf(form: FormState): CarvingRule {
  return (shownValue(form, "threshold") as ThresholdSpec | null)?.method === "headtail" ? "headtail" : "carve_fraction";
}

/**
 * The control of the carving rule: Shadow tolerated (Solar time-based) or Carve amount (Manual); null for Automatic, which has no
 * setting, and for the angle rule.
 */
export function ruleControlOf(form: FormState): SettingView | null {
  const control = thresholdControlOf(form.mode);
  if (control === null || control.name === "threshold") return control;
  return carvingRuleOf(form) === "headtail" ? null : control;
}

/** The carve amount a cutoff stands for among the score points, to a tenth of a percent. */
function carveAmountSetting(ranked: RankedScorePoints, cutoff: number): number {
  return roundedToStep(carveAmountAt(ranked, cutoff), CARVE_AMOUNT_STEP);
}

/**
 * The carve amount (0 to 1) Manual stands at: the carve_fraction setting, a carve amount the threshold itself gives, or for a
 * cutoff the config holds the amount it carves among the score points (null without them).
 */
export function manualCarveAmountOf(form: FormState, ranked: RankedScorePoints | null): number | null {
  const spec = shownValue(form, "threshold") as ThresholdSpec | null;
  if (spec?.method === "cutoff") return ranked === null || typeof spec.value !== "number" ? null : carveAmountSetting(ranked, spec.value);
  if (spec?.method === "carve_fraction" && typeof spec.value === "number") return spec.value;
  const carveAmount = shownValue(form, "carve_fraction");
  return typeof carveAmount === "number" ? carveAmount : null;
}

/** The settings of Manual at a carve amount (0 to 1): the threshold unset, so the engine carves that amount. */
function manualSettings(carveAmount: unknown): Record<string, unknown> {
  return { threshold: null, carve_fraction: carveAmount };
}

/** The number the threshold control shows: the cutoff (0 when unset, as the engine applies it), or the Manual carve amount in %. */
export function thresholdControlNumber(form: FormState, view: SettingView, ranked: RankedScorePoints | null): number {
  if (view.name === "threshold") {
    const spec = shownValue(form, "threshold") as ThresholdSpec | null;
    return spec?.method === "cutoff" && typeof spec.value === "number" ? spec.value : 0;
  }
  const shown = toDisplayValue(view.name, manualCarveAmountOf(form, ranked));
  return typeof shown === "number" ? shown : 0;
}

/** The settings a number of the threshold control stands for: the cutoff (Shadow tolerated), or Manual at that carve amount. */
export function thresholdControlValues(view: SettingView, shownNumber: number): Record<string, unknown> {
  return view.name === "threshold" ? { threshold: { method: "cutoff", value: shownNumber } } : manualSettings(fromDisplayValue(view.name, shownNumber));
}

/**
 * The cutoff the form's threshold settings set: Shadow tolerated, or a cutoff the config holds, as given, and for Manual the cut
 * its carve amount makes among the score points. Null for Automatic, which only the run finds.
 */
export function cutoffTheFormSets(form: FormState, isWeightedMode: boolean, ranked: RankedScorePoints): number | null {
  const spec = shownValue(form, "threshold") as ThresholdSpec | null;
  if (!isWeightedMode || spec?.method === "cutoff") return typeof spec?.value === "number" ? spec.value : 0;
  if (spec?.method === "headtail") return null;
  const carveAmount = manualCarveAmountOf(form, ranked);
  return carveAmount === null ? null : cutoffForCarveAmount(ranked, carveAmount);
}

/**
 * The settings of a cutoff: the cutoff rounded as the slider rounds it. A cutoff reads no carve amount, so the carve amount is
 * unset, as the engine warns about a carve_fraction that its rule does not read.
 */
function cutoffSettings(cutoff: number, highestScore: number): Record<string, unknown> {
  return { threshold: { method: "cutoff", value: roundedToStep(cutoff, cutoffStep(highestScore)) }, carve_fraction: null };
}

/**
 * The settings a cutoff let go on the histogram sets: in a weighted mode Manual at the carve amount it stands for (which takes
 * Automatic to Manual), in Solar time-based the cutoff itself.
 */
export function settingsForCutoff(isWeightedMode: boolean, ranked: RankedScorePoints, cutoff: number, highestScore: number): Record<string, unknown> {
  return isWeightedMode ? manualSettings(carveAmountSetting(ranked, cutoff)) : cutoffSettings(cutoff, highestScore);
}

/** The threshold settings of *values* as one text, to tell whether two sets of settings carve the same. */
function thresholdSettingsKey(values: Record<string, unknown>): string {
  return JSON.stringify(THRESHOLD_SETTINGS.map((name) => values[name] ?? null));
}

interface ThresholdControlProps {
  view: SettingView;
  form: FormState;
  /** The number the form's settings stand for (thresholdControlNumber). */
  storedNumber: number;
  highestScore: number | null;
  autoUpdate: boolean;
  disabled: boolean;
  /** The analysis is out of date: the control is disabled unless it holds an error, which stays open to be fixed. */
  lockedUnlessError?: boolean;
  /** The number the line on the histogram stands for while it is dragged, shown in place of the control's own. */
  previewNumber?: number | null;
  /** The number moved or typed and not handed on yet (auto-update on), or null: the line on the histogram follows it. */
  onHeldNumberChange?: (heldNumber: number | null) => void;
  onChangeValue: (shownNumber: number) => void;
  onCommit: (shownNumber: number) => void;
}

/**
 * The slider and number field of the threshold. With auto-update on, the number moved or typed is held here until the user lets
 * go of the slider or leaves the field, then handed on to run; it shows until the form holds it. A number handed on reaches the
 * form only when its run is next (it may wait behind a run in progress), so going back to the stored number is handed on too
 * while an earlier one is still on its way: it replaces the waiting one, and the run uses the number the user is at.
 */
function ThresholdControl({ view, form, storedNumber: stored, highestScore, autoUpdate, disabled: disabledOtherwise, lockedUnlessError = false, previewNumber = null,
                            onHeldNumberChange, onChangeValue, onCommit }: ThresholdControlProps) {
  const inputId = useId();
  const labelId = `${inputId}-label`;
  const errorId = `${inputId}-error`;
  const [heldNumber, setHeldNumber] = useState<number | null>(null);
  // The number last handed on to run, or the stored number once the form holds a number, however it got there.
  const lastNumberHandedOn = useRef(stored);
  useEffect(() => {
    if (heldNumber === stored) setHeldNumber(null);
    lastNumberHandedOn.current = stored;
  }, [stored]);
  useEffect(() => onHeldNumberChange?.(heldNumber), [heldNumber]);
  useEffect(() => () => onHeldNumberChange?.(null), []);
  // A number refused in the field (above 100 % for Carve amount, below 0) is said under it and never handed on.
  const [refusedInput, setRefusedInput] = useState<string | null>(null);
  const error = refusedInput ?? fieldErrorOf(form, view);
  const disabled = disabledOtherwise || (lockedUnlessError && fieldErrorOf(form, view) === undefined);
  const isCutoff = view.name === "threshold";
  const shownNumber = previewNumber ?? heldNumber ?? stored;
  const highest = isCutoff ? Math.max(highestScore ?? 0, stored) : 100;
  const change = (value: number) => (autoUpdate ? setHeldNumber(value) : onChangeValue(value));
  const commit = () => {
    if (heldNumber === null) return;
    const earlierNumberOnItsWay = lastNumberHandedOn.current !== stored;
    // A number refused in the field is not run; the field already went back to the number before it.
    if (refusedInput === null && (heldNumber !== stored || earlierNumberOnItsWay)) {
      lastNumberHandedOn.current = heldNumber;
      onCommit(heldNumber);
    }
    if (heldNumber === stored) setHeldNumber(null);
  };
  const describedBy = error === undefined ? undefined : errorId;
  return (
    <div className="setting-field threshold-control" data-setting={view.name} data-input-id={inputId}>
      <div className="setting-label-row">
        <label id={labelId} htmlFor={inputId} className="setting-label">{view.label}</label>
        <SettingTooltip settingLabel={view.label} help={view.help} configName={view.name}
                        defaultText={defaultTextOf(view, form, thresholdIsShadowToleratedIn(form.mode))} />
      </div>
      <div className="setting-control">
        <input type="range" className="setting-range" min={0} max={highest} step={isCutoff ? cutoffStep(highest) : 1} value={Math.min(shownNumber, highest)}
               aria-labelledby={labelId} aria-describedby={describedBy} disabled={disabled}
               onChange={(event) => change(Number(event.target.value))} onPointerUp={commit}
               onKeyUp={(event) => { if (SLIDER_KEYS.has(event.key)) commit(); }} />
        <span className="threshold-number" onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") commit(); }}>
          <NumberInput id={inputId} className="setting-number setting-number-short" value={shownNumber} mayBeEmpty={false} minimum={0}
                       maximum={isCutoff ? undefined : 100} invalid={error !== undefined} describedBy={describedBy} disabled={disabled}
                       onValue={(typed) => change(typed!)} onRefused={setRefusedInput} />
        </span>
        <span className="setting-unit">{view.unit}</span>
      </div>
      {isCutoff && (
        <div className="threshold-slider-ends" aria-hidden="true">
          <span>{messages.sliderLowestEnd}</span>
          <span>{messages.sliderHighestScore(withUnit(formattedNumber(highest), view.unit))}</span>
        </div>
      )}
      {error !== undefined && <p id={errorId} className="setting-error"><WarningIcon /><span>{error}</span></p>}
    </div>
  );
}

interface CarvingRuleChoiceProps {
  mode: string;
  rule: CarvingRule;
  disabled: boolean;
  onChoose: (rule: CarvingRule) => void;
}

/** The carving rule of a weighted mode (UX 5.5): Manual or Automatic, side by side at the top. */
function CarvingRuleChoice({ mode, rule, disabled, onChoose }: CarvingRuleChoiceProps) {
  const labelId = useId();
  const view = settingView("threshold", mode);
  return (
    <div className="setting-field carving-rule-choice" data-setting="threshold">
      {/* The panel's section is titled Carving rule already: the label names the choice for screen readers. */}
      <span id={labelId} className="setting-label visually-hidden">{view.label}</span>
      <div role="radiogroup" aria-labelledby={labelId} className="carving-rule-options">
        {CARVING_RULES.map((choice) => (
          <label key={choice}>
            <input type="radio" name={labelId} value={choice} checked={rule === choice} disabled={disabled} onChange={() => onChoose(choice)} />
            {messages.carvingRuleChoices[choice]}
          </label>
        ))}
      </div>
      {/* Its "i" beside Manual | Automatic, after them in the reading and tab order as on the screen */}
      <SettingTooltip settingLabel={view.label} help={view.help} configName="threshold" defaultText={messages.carvingRuleChoices.carve_fraction} />
    </div>
  );
}

/**
 * A key number on chrome (UX 5.5, 5.6): its label, with an "i" that says what it counts when *help* is given, then the value; the
 * unit may wrap under the value in a narrow tile. A *note* under the value says what the number is a share of.
 */
export function NumberTile({ label, value, unit, help, note }: { label: string; value: string; unit?: string; help?: string; note?: string }) {
  return (
    <div className="number-tile">
      <span className="number-tile-label">{label}{help !== undefined && <> <SettingTooltip settingLabel={label} help={help} /></>}</span>
      <span className="number-tile-value">{value}{unit && <> <span className="number-tile-unit">{unit}</span></>}</span>
      {note !== undefined && <span className="number-tile-note">{note}</span>}
    </div>
  );
}

interface CarvingNumbersProps {
  summary: CarvingSummary;
  voxelSize: number | null;
  isWeighted: boolean;
  lastAnalysisSeconds: number | null;
}

/**
 * Kept here (this criterion's kept volume, with its share of what reached it), Obstruction removed (weighted modes) and the time of
 * the last analysis, two per row. What the chain kept in all is under the cards (chainSummaryLine), not here.
 */
export function CarvingNumbers({ summary, voxelSize, isWeighted, lastAnalysisSeconds }: CarvingNumbersProps) {
  const { units } = messages;
  const keptShare = messages.keptHereShare(formatPercent(summary.retention_pct));
  return (
    <div className="number-tiles number-tiles-two">
      {voxelSize !== null
        ? <NumberTile label={messages.keptHere} value={formatNumber(summary.voxels_kept * voxelSize ** 3)} unit={units.cubicMetres} note={keptShare} />
        : <NumberTile label={messages.keptHere} value={formatNumber(Math.round(summary.retention_pct))} unit={units.percent}
                      note={messages.keptHereOfWhatReached} />}
      {isWeighted && summary.obstruction_fraction_carved !== null && (
        <NumberTile label={messages.obstructionRemoved} value={formatNumber(summary.obstruction_fraction_carved * 100)} unit={units.percent} />
      )}
      {lastAnalysisSeconds !== null && (
        <NumberTile label={messages.lastAnalysisTook} value={formatNumber(lastAnalysisSeconds, undefined, 1)} unit={units.seconds} />
      )}
    </div>
  );
}

export interface CarvingStepProps {
  form: FormState;
  isWeightedMode: boolean;
  summary: CarvingSummary | null;
  scorePoints: ScorePoints | null;
  /** The analysis is out of date (preprocessing not current): the carving is locked until it runs again. */
  analysisOutOfDate: boolean;
  /** The carving shown is out of date or being replaced: drawn dimmed. */
  carvingDimmed: boolean;
  autoUpdate: boolean;
  onAutoUpdateChange: (on: boolean) => void;
  /** Why the threshold cannot be changed now (a run other than a carving update, or the analysis out of date); null when it can. */
  thresholdDisabledReason: string | null;
  /** Why the other carving settings cannot be changed now (a run of the project); null when they can. */
  settingsDisabledReason: string | null;
  /** Why a run cannot start (another run, inputs, settings, the warm-up); null when it can. */
  runBlocker: string | null;
  onChange: (values: Record<string, unknown>) => void;
  /** The threshold settings to apply and run, with auto-update on: the rule, its cutoff, or the carve amount. */
  onThresholdCommit: (values: Record<string, unknown>) => void;
  /** A carving setting was changed with auto-update on and the user is done with it: the carving reruns with it. */
  onCarvingSettingCommit: () => void;
  onUpdateCarving: () => void;
  lastAnalysisSeconds: number | null;
  /** Whether the reason the controls are disabled is written over them; false where Run analysis says it (the Criteria step's pinned bar). */
  showsDisabledReason?: boolean;
}

/** A cutoff let go on the histogram: drawn until the carving it starts comes back, while the form holds the settings before it or those it set. */
interface ReleasedCutoff {
  cutoff: number;
  settingsKeys: string[];
}

export function CarvingStep(props: CarvingStepProps) {
  const { form, summary, scorePoints, analysisOutOfDate, autoUpdate, runBlocker, isWeightedMode } = props;
  const updateReasonId = useId();
  const settingChangedSinceCommit = useRef(false);
  const [draggedCutoff, setDraggedCutoff] = useState<number | null>(null);
  const [heldControlNumber, setHeldControlNumber] = useState<number | null>(null);
  const [released, setReleased] = useState<ReleasedCutoff | null>(null);
  const [switchedFromAutomatic, setSwitchedFromAutomatic] = useState(false);
  useEffect(() => setReleased(null), [summary]);
  const comparedScores = scorePoints?.comparedScores ?? null;
  const kept = scorePoints?.kept ?? null;
  const ranked = useMemo(() => (scorePoints !== null && comparedScores !== null ? rankScorePoints(comparedScores, scorePoints.scores) : null),
                         [scorePoints]);
  const scoreUnit = scorePoints?.header.score_unit ?? "";
  // The end of the Shadow tolerated slider: the highest score the cutoff is compared with, above which a cutoff carves nothing more;
  // the highest raw score until a carving has run on this analysis.
  const highestScore = scorePoints?.header.compared_score_max ?? scorePoints?.header.score_max ?? null;
  const thresholdView = thresholdControlOf(form.mode);
  const rule = carvingRuleOf(form);
  const ruleControl = ruleControlOf(form);
  const groups = settingsForStep("carving", form.mode).map((group) => ({
    ...group, essential: [], folded: group.folded.filter((view) => view.name !== "threshold"),
    foldLabel: messages.moreSettingsOfGroup[group.title as keyof typeof messages.moreSettingsOfGroup] ?? group.foldLabel,
  }));
  const thresholdDisabled = props.thresholdDisabledReason !== null;
  // While the analysis is out of date the carving settings wait for Run analysis, except one with an error, which stays open to
  // be fixed (SettingGroup fieldsWithErrorEditable); a change there is saved but runs nothing.
  const settingsDisabled = analysisOutOfDate || props.settingsDisabledReason !== null;
  const fieldsWithErrorEditable = analysisOutOfDate && props.settingsDisabledReason === null;
  // The angle rule has no threshold, so nothing updates on its own there: Update carving runs it.
  const autoUpdating = autoUpdate && thresholdView !== null;
  const applyThreshold = (values: Record<string, unknown>) => (autoUpdating ? props.onThresholdCommit(values) : props.onChange(values));
  // Every change goes to the form at once; with auto-update on the run follows when the user is done with the field, so typing
  // "45" saves and runs 45, not 4 (a run disables the settings and would take the focus away mid-number).
  const changeCarvingSetting = (values: Record<string, unknown>) => {
    props.onChange(values);
    if (autoUpdating) settingChangedSinceCommit.current = true;
  };
  const commitCarvingSetting = () => {
    if (!settingChangedSinceCommit.current) return;
    settingChangedSinceCommit.current = false;
    if (!analysisOutOfDate) props.onCarvingSettingCommit();
  };
  const isNumberField = (target: EventTarget) => target instanceof HTMLInputElement && target.type === "number";
  const commitChoice = (event: FormEvent) => {
    const target = event.target;
    if (target instanceof HTMLSelectElement || (target instanceof HTMLInputElement && (target.type === "checkbox" || target.type === "radio"))) commitCarvingSetting();
  };
  // A slider runs once the user lets it go, or after a key moved it, as the threshold slider does: not on every step of a drag.
  // Leaving it runs a move not run yet (a drag let go outside the window).
  const isSlider = (target: EventTarget) => target instanceof HTMLInputElement && target.type === "range";
  const commitNumberOnLeave = (event: FocusEvent) => { if (isNumberField(event.target) || isSlider(event.target)) commitCarvingSetting(); };
  const commitNumberOnEnter = (event: KeyboardEvent) => { if (event.key === "Enter" && isNumberField(event.target)) commitCarvingSetting(); };
  const commitSliderOnRelease = (event: PointerEvent) => { if (isSlider(event.target)) commitCarvingSetting(); };
  const commitSliderAfterKey = (event: KeyboardEvent) => { if (SLIDER_KEYS.has(event.key) && isSlider(event.target)) commitCarvingSetting(); };
  const disabledReason = analysisOutOfDate ? null : (props.thresholdDisabledReason ?? props.settingsDisabledReason);
  const updateBlocker = analysisOutOfDate ? null : runBlocker;
  const resultsClassName = props.carvingDimmed || analysisOutOfDate ? "carving-content carving-content-dimmed" : "carving-content";
  const thresholdLocked = thresholdDisabled || analysisOutOfDate;

  // The cutoff on the histogram: dragged, moved on the slider or typed and not handed on yet, let go and on its way to a run, set
  // in the form since the carving shown (dimmed, or a change not stored yet), or the last carving's. Any but the last is a preview.
  const heldCutoff = heldControlNumber === null || ranked === null || ruleControl === null ? null
    : ruleControl.name === "carve_fraction" ? cutoffForCarveAmount(ranked, heldControlNumber / 100) : heldControlNumber;
  const settingsKey = thresholdSettingsKey(form.userValues);
  const formDiffersFromCarving = props.carvingDimmed || settingsKey !== thresholdSettingsKey(form.stored.values);
  const releasedCutoff = released !== null && released.settingsKeys.includes(settingsKey) ? released.cutoff : null;
  const formCutoff = formDiffersFromCarving && ranked !== null ? cutoffTheFormSets(form, isWeightedMode, ranked) : null;
  const shownCutoff = summary === null ? null : draggedCutoff ?? heldCutoff ?? releasedCutoff ?? formCutoff ?? summary.threshold_value;
  const cutoffIsPreview = summary !== null && shownCutoff !== summary.threshold_value;
  const cutoffText = (cutoff: number) => withUnit(formattedNumber(cutoff), scoreUnit);
  const keptText = (cutoff: number) => formatNumber(keptShareAt(ranked!, cutoff) * 100, messages.units.percent);
  const carveAmountText = (amount: number) => formatNumber(amount * 100, messages.units.percent);
  const formCarveAmount = manualCarveAmountOf(form, ranked);
  let previewNote: string | null = null;
  if (cutoffIsPreview && ranked !== null && shownCutoff !== null) {
    const amount = draggedCutoff !== null ? carveAmountAt(ranked, draggedCutoff) : heldControlNumber !== null ? heldControlNumber / 100
      : formCarveAmount;
    // In the weighted modes a cut stands for a carve amount, also under Automatic, which letting go of the line turns into Manual.
    previewNote = isWeightedMode && amount !== null ? messages.cutoffPreviewWithCarveAmount(carveAmountText(amount), cutoffText(shownCutoff), keptText(shownCutoff))
      : messages.cutoffPreview(cutoffText(shownCutoff), keptText(shownCutoff));
  }
  // While the line is dragged, the control of the rule shows the number it stands for.
  const previewNumber = draggedCutoff === null || ranked === null || ruleControl === null ? null
    : ruleControl.name === "carve_fraction" ? roundedToStep(carveAmountAt(ranked, draggedCutoff) * 100, CARVE_AMOUNT_STEP * 100)
    : roundedToStep(draggedCutoff, cutoffStep(highestScore ?? 0));
  const releaseCutoff = (cutoff: number) => {
    setDraggedCutoff(null);
    if (ranked === null) return;
    const values = settingsForCutoff(isWeightedMode, ranked, cutoff, highestScore ?? 0);
    const settingsKeyAfter = thresholdSettingsKey({ ...form.userValues, ...values });
    if (settingsKeyAfter === settingsKey) return;          // let go where it started: nothing to run
    setReleased({ cutoff, settingsKeys: [settingsKey, settingsKeyAfter] });
    if (isWeightedMode && rule === "headtail") setSwitchedFromAutomatic(true);
    applyThreshold(values);
  };
  // Choosing Manual keeps the cut where it is: it starts from the amount the cutoff on the histogram carves (the mode's own amount
  // without a cut to start from). Automatic reads no carve amount.
  const chooseRule = (next: CarvingRule) => {
    setSwitchedFromAutomatic(false);
    if (next === "headtail") applyThreshold({ threshold: { method: "headtail" }, carve_fraction: null });
    else applyThreshold(ranked === null || shownCutoff === null ? { threshold: null } : settingsForCutoff(true, ranked, shownCutoff, 0));
  };
  const automaticLine = summary !== null && !formDiffersFromCarving ? messages.automaticCut(cutoffText(summary.threshold_value))
    : messages.automaticBeforeCarving;
  return (
    <div className="carving-step">
      {analysisOutOfDate && (
        <div className="carving-locked">
          <p className="step-reason">{messages.analysisOutOfDate}</p>
        </div>
      )}
      {disabledReason !== null && (props.showsDisabledReason ?? true) && <p className="step-reason">{disabledReason}</p>}
      {/* Only the results of the carving are dimmed (UX 5.5, 6.3); the controls are disabled instead, so their labels, the reasons
          and the messages of settings to fix keep their contrast next to what they explain (UX 12). */}
      <div className="carving-content">
        {thresholdView === null ? <p className="step-reason">{messages.angleRuleHasNoThreshold}</p> : (
          <>
            {isWeightedMode && <CarvingRuleChoice mode={form.mode} rule={rule} disabled={thresholdLocked} onChoose={chooseRule} />}
            {switchedFromAutomatic && rule === "carve_fraction" && <p className="step-reason">{messages.ruleSwitchedToManual}</p>}
            {ruleControl === null ? <p className="step-reason">{automaticLine}</p> : (
              <ThresholdControl key={ruleControl.name} view={ruleControl} form={form} storedNumber={thresholdControlNumber(form, ruleControl, ranked)}
                                highestScore={highestScore} autoUpdate={autoUpdating}
                                disabled={thresholdDisabled} lockedUnlessError={analysisOutOfDate} previewNumber={previewNumber}
                                onHeldNumberChange={setHeldControlNumber}
                                onChangeValue={(shownNumber) => props.onChange(thresholdControlValues(ruleControl, shownNumber))}
                                onCommit={(shownNumber) => props.onThresholdCommit(thresholdControlValues(ruleControl, shownNumber))} />
            )}
            <label className="switch-row">
              <input type="checkbox" role="switch" className="setting-switch" checked={autoUpdate} disabled={analysisOutOfDate}
                     onChange={(event) => props.onAutoUpdateChange(event.target.checked)} />
              {messages.updateWhenThresholdChanges}
            </label>
          </>
        )}
      </div>
      {!autoUpdating && (
        <div className="update-carving">
          <button type="button" className="secondary-button" disabled={runBlocker !== null || analysisOutOfDate}
                  aria-describedby={updateBlocker !== null ? updateReasonId : undefined} onClick={props.onUpdateCarving}>
            {messages.updateCarving}
          </button>
          {updateBlocker !== null && <p id={updateReasonId} className="run-button-reason">{updateBlocker}</p>}
        </div>
      )}
      {summary !== null && (
        <div className={resultsClassName}>
          {thresholdView !== null && comparedScores !== null && kept !== null && shownCutoff !== null && (
            <ScoreHistogram comparedScores={comparedScores} kept={kept} cutoff={shownCutoff} carvingCutoff={summary.threshold_value}
                            cutoffIsPreview={cutoffIsPreview} unit={scoreUnit}
                            axisTitle={messages.scoreOfModeWithUnit(scorePoints?.header.mode ?? form.mode, scoreUnit)}
                            slopeLimitVoxelsRemoved={summary.slope_limit_extra_voxels_removed} previewNote={previewNote}
                            cutoffValueText={(cutoff) => messages.cutoffHandleValue(cutoffText(cutoff), keptText(cutoff))}
                            cutoffDisabled={thresholdLocked || ranked === null} onCutoffMove={setDraggedCutoff} onCutoffRelease={releaseCutoff} />
          )}
          <CarvingNumbers summary={summary} voxelSize={scorePoints?.header.voxel_size ?? null} isWeighted={isWeightedMode}
                          lastAnalysisSeconds={props.lastAnalysisSeconds} />
        </div>
      )}
      <div className="carving-settings" onChange={commitChoice} onBlur={commitNumberOnLeave} onKeyDown={commitNumberOnEnter}
           onPointerUp={commitSliderOnRelease} onKeyUp={commitSliderAfterKey}>
        {groups.map((group) => (
          <SettingGroup key={group.title} group={group} form={form} onChange={changeCarvingSetting} disabled={settingsDisabled}
                        fieldsWithErrorEditable={fieldsWithErrorEditable} />
        ))}
      </div>
    </div>
  );
}
