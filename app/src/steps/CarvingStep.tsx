// The Carving step (UX 5.5, 11): the threshold control of the mode (Shadow tolerated in m²·h with its slider for Sun at set
// hours, Carve amount in % for the weighted modes, the angle rule's message), the other carving settings folded under it, the
// histogram, the numbers of the last carving, and the "Update when I change the threshold" switch, remembered per project.
// With the switch on, letting go of the slider or leaving the number field reruns the carving, as does a change of another
// carving setting (a switch or a choice at once, a number field when the user leaves it); off, Update carving does.
// When the analysis is out of date the histogram and numbers of the last carving are shown dimmed, its controls disabled, with Run
// analysis in the step.
import { useEffect, useId, useRef, useState, type FocusEvent, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import type { RunSummary } from "../api_client/client";
import { messages } from "../messages";
import { shownValue, type FormState } from "../settings_form/form_state";
import { fromDisplayValue, settingsForStep, thresholdIsShadowToleratedIn, toDisplayValue, type SettingView } from "../settings_form/presentation";
import { defaultTextOf, fieldErrorOf, WarningIcon } from "../settings_form/SettingField";
import { SettingGroup } from "../settings_form/SettingGroup";
import { SettingTooltip } from "../settings_form/SettingTooltip";
import { NumberInput } from "../settings_form/widgets/NumberInput";
import type { ThresholdSpec } from "../settings_form/widgets/ThresholdRule";
import type { ScorePoints } from "../viewer/score_points_decoder";
import { formatNumber, formattedNumber } from "./format_numbers";
import { ScoreHistogram } from "./ScoreHistogram";
import "./steps.css";

type CarvingSummary = NonNullable<RunSummary["carving"]>;

const AUTO_UPDATE_STORAGE_PREFIX = "usc.autoUpdate.";
const SLIDER_STEPS = 100;
const CARVING_GROUP = "How much to carve";
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

/** The number the threshold control shows: the cutoff in m²·h (0 when unset, as the engine applies it), or the carve amount in %. */
export function thresholdControlNumber(form: FormState, view: SettingView): number {
  const value = shownValue(form, view.name);
  if (view.name === "threshold") {
    const spec = value as ThresholdSpec | null;
    return spec?.method === "cutoff" && typeof spec.value === "number" ? spec.value : 0;
  }
  const shown = toDisplayValue(view.name, value);
  return typeof shown === "number" ? shown : 0;
}

/** The settings a number of the threshold control stands for. */
export function thresholdControlValues(view: SettingView, shownNumber: number): Record<string, unknown> {
  return view.name === "threshold" ? { threshold: { method: "cutoff", value: shownNumber } } : { [view.name]: fromDisplayValue(view.name, shownNumber) };
}

/**
 * Why Carve amount is disabled: the carving rule chosen in the fold (Automatic split, Score cutoff) sets the cutoff without it.
 * Null when the control is not Carve amount or the rule is Carve amount.
 */
export function carveAmountUnusedReason(form: FormState, view: SettingView): string | null {
  if (view.name !== "carve_fraction") return null;
  const method = (shownValue(form, "threshold") as ThresholdSpec | null)?.method ?? "carve_fraction";
  return method === "carve_fraction" ? null : messages.carveAmountNotUsed(messages.carvingRuleChoices[method]);
}

/** A slider step a hundredth of the range or less, rounded down to a power of ten. */
function sliderStep(highest: number): number {
  return highest > 0 ? 10 ** Math.floor(Math.log10(highest / SLIDER_STEPS)) : 1;
}

interface ThresholdControlProps {
  view: SettingView;
  form: FormState;
  highestScore: number | null;
  autoUpdate: boolean;
  disabled: boolean;
  /** The element that says why the control is disabled, when it is not a run (Carve amount under another carving rule). */
  reasonId?: string;
  /** The analysis is out of date: the control is disabled unless it holds an error, which stays open to be fixed. */
  lockedUnlessError?: boolean;
  onChangeValue: (shownNumber: number) => void;
  onCommit: (shownNumber: number) => void;
}

/**
 * The slider and number field of the threshold. With auto-update on, the number moved or typed is held here until the user lets
 * go of the slider or leaves the field, then handed on to run; it shows until the form holds it. A number handed on reaches the
 * form only when its run is next (it may wait behind a run in progress), so going back to the stored number is handed on too
 * while an earlier one is still on its way: it replaces the waiting one, and the run uses the number the user is at.
 */
function ThresholdControl({ view, form, highestScore, autoUpdate, disabled: disabledOtherwise, reasonId, lockedUnlessError = false, onChangeValue,
                            onCommit }: ThresholdControlProps) {
  const inputId = useId();
  const labelId = `${inputId}-label`;
  const errorId = `${inputId}-error`;
  const stored = thresholdControlNumber(form, view);
  const [heldNumber, setHeldNumber] = useState<number | null>(null);
  // The number last handed on to run, or the stored number once the form holds a number, however it got there.
  const lastNumberHandedOn = useRef(stored);
  useEffect(() => {
    if (heldNumber === stored) setHeldNumber(null);
    lastNumberHandedOn.current = stored;
  }, [stored]);
  // A number refused in the field (above 100 % for Carve amount, below 0) is said under it and never handed on.
  const [refusedInput, setRefusedInput] = useState<string | null>(null);
  const error = refusedInput ?? fieldErrorOf(form, view);
  const disabled = disabledOtherwise || (lockedUnlessError && fieldErrorOf(form, view) === undefined);
  const isShadowTolerated = view.name === "threshold";
  const shownNumber = heldNumber ?? stored;
  const highest = isShadowTolerated ? Math.max(highestScore ?? 0, stored) : 100;
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
  const describedBy = [error === undefined ? null : errorId, reasonId ?? null].filter((id) => id !== null).join(" ") || undefined;
  return (
    <div className="setting-field threshold-control" data-setting={view.name}>
      <div className="setting-label-row">
        <label id={labelId} htmlFor={inputId} className="setting-label">{view.label}</label>
        <SettingTooltip settingLabel={view.label} help={view.help} configName={view.name} defaultText={defaultTextOf(view, form, isShadowTolerated)} />
      </div>
      <div className="setting-control">
        <input type="range" className="setting-range" min={0} max={highest} step={isShadowTolerated ? sliderStep(highest) : 1} value={Math.min(shownNumber, highest)}
               aria-labelledby={labelId} aria-describedby={describedBy} disabled={disabled}
               onChange={(event) => change(Number(event.target.value))} onPointerUp={commit}
               onKeyUp={(event) => { if (SLIDER_KEYS.has(event.key)) commit(); }} />
        <span className="threshold-number" onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") commit(); }}>
          <NumberInput id={inputId} className="setting-number setting-number-short" value={shownNumber} mayBeEmpty={false} minimum={0}
                       maximum={isShadowTolerated ? undefined : 100} invalid={error !== undefined} describedBy={describedBy} disabled={disabled}
                       onValue={(typed) => change(typed!)} onRefused={setRefusedInput} />
        </span>
        <span className="setting-unit">{view.unit}</span>
      </div>
      {isShadowTolerated && (
        <div className="threshold-slider-ends" aria-hidden="true">
          <span>{messages.sliderLowestEnd}</span>
          <span>{messages.sliderHighestScore(formattedNumber(highest))}</span>
        </div>
      )}
      {error !== undefined && <p id={errorId} className="setting-error"><WarningIcon /><span>{error}</span></p>}
    </div>
  );
}

/** A key number on chrome (UX 5.5, 5.6): its label, then the value; the unit may wrap under the value in a narrow tile. */
export function NumberTile({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="number-tile">
      <span className="number-tile-label">{label}</span>
      <span className="number-tile-value">{value}{unit && <> <span className="number-tile-unit">{unit}</span></>}</span>
    </div>
  );
}

interface CarvingNumbersProps {
  summary: CarvingSummary;
  voxelSize: number | null;
  isWeighted: boolean;
  lastAnalysisSeconds: number | null;
}

/** Volume kept, Volume carved, Kept volume, Obstruction removed (weighted modes) and the time of the last analysis, two per row. */
export function CarvingNumbers({ summary, voxelSize, isWeighted, lastAnalysisSeconds }: CarvingNumbersProps) {
  const { units } = messages;
  // Carved is 100 minus the kept percentage as shown, so the two whole numbers always add up to 100.
  const keptPercent = Math.round(summary.retention_pct);
  return (
    <div className="number-tiles number-tiles-two">
      <NumberTile label={messages.volumeKept} value={formatNumber(keptPercent)} unit={units.percent} />
      <NumberTile label={messages.volumeCarved} value={formatNumber(100 - keptPercent)} unit={units.percent} />
      {voxelSize !== null && <NumberTile label={messages.keptVolume} value={formatNumber(summary.voxels_kept * voxelSize ** 3)} unit={units.cubicMetres} />}
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
  /** The threshold to apply and run, with auto-update on, as the control shows it (m²·h, or % for Carve amount). */
  onThresholdCommit: (shownNumber: number) => void;
  /** A carving setting was changed with auto-update on and the user is done with it: the carving reruns with it. */
  onCarvingSettingCommit: () => void;
  onUpdateCarving: () => void;
  onRunAnalysis: () => void;
  lastAnalysisSeconds: number | null;
  /** The progress and outcome of a carving update, shown under the control or the Update carving button. */
  carvingFeedback: ReactNode;
  /** The progress and outcome of the step's own Run analysis. */
  analysisFeedback: ReactNode;
}

export function CarvingStep(props: CarvingStepProps) {
  const { form, summary, scorePoints, analysisOutOfDate, autoUpdate, runBlocker } = props;
  const reasonId = useId();
  const updateReasonId = useId();
  const carveAmountReasonId = useId();
  const settingChangedSinceCommit = useRef(false);
  const thresholdView = thresholdControlOf(form.mode);
  const isShadowTolerated = thresholdIsShadowToleratedIn(form.mode);
  const groups = settingsForStep("carving", form.mode).map((group) => ({
    ...group, essential: [], foldLabel: messages.moreSettingsOfGroup[group.title as keyof typeof messages.moreSettingsOfGroup] ?? group.foldLabel,
  }));
  const thresholdDisabled = props.thresholdDisabledReason !== null;
  // While the analysis is out of date the carving settings wait for Run analysis, except one with an error, which stays open to
  // be fixed (SettingGroup fieldsWithErrorEditable); a change there is saved but runs nothing.
  const settingsDisabled = analysisOutOfDate || props.settingsDisabledReason !== null;
  const fieldsWithErrorEditable = analysisOutOfDate && props.settingsDisabledReason === null;
  // The angle rule has no threshold, so nothing updates on its own there: Update carving runs it.
  const autoUpdating = autoUpdate && thresholdView !== null;
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
  const commitNumberOnLeave = (event: FocusEvent) => { if (isNumberField(event.target)) commitCarvingSetting(); };
  const commitNumberOnEnter = (event: KeyboardEvent) => { if (event.key === "Enter" && isNumberField(event.target)) commitCarvingSetting(); };
  const disabledReason = analysisOutOfDate ? null : (props.thresholdDisabledReason ?? props.settingsDisabledReason);
  const carveAmountReason = thresholdView === null ? null : carveAmountUnusedReason(form, thresholdView);
  const updateBlocker = analysisOutOfDate ? null : runBlocker;
  const resultsClassName = props.carvingDimmed || analysisOutOfDate ? "carving-content carving-content-dimmed" : "carving-content";
  const comparedScores = scorePoints?.comparedScores ?? null;
  const kept = scorePoints?.kept ?? null;
  return (
    <div className="carving-step">
      {analysisOutOfDate && (
        <div className="carving-locked">
          <p className="step-reason">{messages.analysisOutOfDate}</p>
          <button type="button" className="primary-button" disabled={runBlocker !== null} aria-describedby={runBlocker !== null ? reasonId : undefined}
                  onClick={props.onRunAnalysis}>
            {messages.runAnalysis}
          </button>
          {runBlocker !== null && <p id={reasonId} className="run-button-reason">{runBlocker}</p>}
        </div>
      )}
      {props.analysisFeedback}
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
      {carveAmountReason !== null && <p id={carveAmountReasonId} className="step-reason">{carveAmountReason}</p>}
      {/* Only the results of the carving are dimmed (UX 5.5, 6.3); the controls are disabled instead, so their labels, the reasons
          and the messages of settings to fix keep their contrast next to what they explain (UX 12). */}
      <div className="carving-content">
        {thresholdView === null ? <p className="step-reason">{messages.angleRuleHasNoThreshold}</p> : (
          <ThresholdControl view={thresholdView} form={form} highestScore={scorePoints?.header.score_max ?? null} autoUpdate={autoUpdating}
                            disabled={thresholdDisabled || carveAmountReason !== null} lockedUnlessError={analysisOutOfDate}
                            reasonId={carveAmountReason !== null ? carveAmountReasonId : undefined}
                            onChangeValue={(shownNumber) => props.onChange(thresholdControlValues(thresholdView, shownNumber))}
                            onCommit={props.onThresholdCommit} />
        )}
        <div className="carving-settings" onChange={commitChoice} onBlur={commitNumberOnLeave} onKeyDown={commitNumberOnEnter}>
          {groups.map((group) => (
            <SettingGroup key={group.title} group={group} form={form} onChange={changeCarvingSetting} disabled={settingsDisabled}
                          fieldsWithErrorEditable={fieldsWithErrorEditable} />
          ))}
        </div>
        {thresholdView !== null && (
          <label className="switch-row">
            <input type="checkbox" role="switch" className="setting-switch" checked={autoUpdate} disabled={analysisOutOfDate}
                   onChange={(event) => props.onAutoUpdateChange(event.target.checked)} />
            {messages.updateWhenThresholdChanges}
          </label>
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
      {props.carvingFeedback}
      {summary !== null && (
        <div className={resultsClassName}>
          {thresholdView !== null && comparedScores !== null && kept !== null && (
            <ScoreHistogram comparedScores={comparedScores} kept={kept} cutoff={summary.threshold_value} isShadowTolerated={isShadowTolerated}
                            slopeLimitVoxelsRemoved={summary.slope_limit_extra_voxels_removed} />
          )}
          <CarvingNumbers summary={summary} voxelSize={scorePoints?.header.voxel_size ?? null} isWeighted={props.isWeightedMode}
                          lastAnalysisSeconds={props.lastAnalysisSeconds} />
        </div>
      )}
    </div>
  );
}
