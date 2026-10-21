// One setting in the form (UX 7, 11): its plain label with the "i" of its tooltip, the control with the unit beside the value,
// and, after a rejected save, the message under it with a warning icon and the field outlined in the error colour.
import { useId, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { formattedNumber, withUnit } from "../steps/format_numbers";
import { plainModeName } from "../steps/step_summaries";
import type { ColdPeriodState, Hemisphere } from "./analysis_period";
import { defaultValue, shownValue, type FormState, type SchemaProperty } from "./form_state";
import {
  ANALYSIS_PERIOD_FIELDS, BALANCE_TEMPERATURE_FIELDS, fromDisplayValue, settingsOfField, shownSliderOf, thresholdIsShadowToleratedIn,
  toDisplayValue, unitBesideValue, type SettingView,
} from "./presentation";
import { SettingTooltip } from "./SettingTooltip";
import { AnalysisPeriod, type AnalysisPeriodField } from "./widgets/AnalysisPeriod";
import { BalanceTemperatureSlider } from "./widgets/BalanceTemperatureSlider";
import { MeshFormat } from "./widgets/MeshFormat";
import { NumberInput, type ControlProps, type NumberRange } from "./widgets/NumberInput";
import { RangeSlider, spokenValue, type AutomaticValue } from "./widgets/RangeSlider";
import { SunStepsPerHour } from "./widgets/SunStepsPerHour";
import { ThresholdRule, type ThresholdSpec } from "./widgets/ThresholdRule";
import { TiltedPlaneAngles } from "./widgets/TiltedPlaneAngles";
import "./settings_form.css";

/** What a step adds under one of its fields: quiet lines, under its error too (the grid and the sample spacing under Voxel
 *  size), and the error in the step's own words in place of the engine's message (the grid over the budget). */
export interface SettingFieldExtras {
  notes?: ReactNode[];
  errorContent?: ReactNode;
  /** The cold period of the weather file, for the period control's preset in Solar usefulness; null or absent in the other modes. */
  coldPeriod?: ColdPeriodState | null;
  /** The hemisphere of the weather file, for the period control's heating season preset; northern when absent. */
  hemisphere?: Hemisphere;
}

export interface SettingFieldProps {
  view: SettingView;
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  disabled?: boolean;
  extras?: SettingFieldExtras;
}

// The words shown for the options of a choice the engine names in code.
const CHOICE_NAMES: Record<string, Record<string, string>> = {
  plate_stacking: messages.floorStackingChoices, time_basis: messages.timeBasisChoices,
};

/** The messages of the last rejected save for the settings *view* draws (the six of the analysis period), or undefined. */
export function fieldErrorOf(form: FormState, view: SettingView): string | undefined {
  const errors = settingsOfField(view.name).map((name) => form.fieldErrors[name]).filter((error) => error !== undefined);
  return errors.length === 0 ? undefined : errors.join(" ");
}

/** The types a schema property allows, its "anyOf" members included. */
function typesOf(property: SchemaProperty | undefined): (string | undefined)[] {
  if (property === undefined) return [];
  return property.anyOf ? property.anyOf.map((member) => member.type) : [property.type];
}

/** The engine's bounds of a number setting, the exclusive ones ("more than 0", "less than 360") included. */
export function rangeOf(property: SchemaProperty | undefined): NumberRange {
  const bounded = property?.anyOf?.find((member) => member.type === "number" || member.type === "integer") ?? property;
  return { minimum: bounded?.minimum, maximum: bounded?.maximum, exclusiveMinimum: bounded?.exclusiveMinimum, exclusiveMaximum: bounded?.exclusiveMaximum };
}

/**
 * The grid line of Voxel size (under the field and in its tooltip): the grid last planned. A refused save plans none, so while
 * the voxel size shown is not the one planned the line says it is the grid of the saved one. Null without a plan.
 */
export function gridLineOf(form: FormState): string | null {
  const plan = form.gridPlan;
  if (plan === null) return null;
  if (shownValue(form, "voxel_size") === plan.voxel_size) return messages.gridSize(plan.resolution, plan.total_voxels);
  return messages.gridSizeAtSavedVoxelSize(withUnit(formattedNumber(plan.voxel_size), "m"), plan.resolution, plan.total_voxels);
}

// The engine's automatic slope limit of the weighted modes, as the description of max_slope_deg in GET schema states it
// (resolve_max_slope_deg; SettingGroup.test.ts checks the two agree).
const AUTOMATIC_SLOPE_LIMIT_IN_DESCRIPTION = /None \(default\): (\d+(?:\.\d+)?) for the weighted modes/;

/**
 * What an empty setting does in the form's mode, for a setting whose empty value the engine fills by mode, or null. The slope
 * limit is the one: the engine's number in the weighted modes, off in Solar time-based and the angle rule (score smoothing says
 * it in its help). Null in a weighted mode when the schema does not give the number.
 */
export function emptyMeaningOf(view: SettingView, form: Pick<FormState, "mode" | "scoreKindByMode" | "schemaProperties">): string | null {
  if (view.name !== "max_slope_deg") return null;
  if (form.scoreKindByMode[form.mode] !== "weighted_sum") return messages.emptyMeansInMode(messages.switchedOff, plainModeName(form.mode));
  const degrees = AUTOMATIC_SLOPE_LIMIT_IN_DESCRIPTION.exec(form.schemaProperties.max_slope_deg?.description ?? "")?.[1];
  return degrees === undefined ? null : messages.emptyMeansInMode(withUnit(formattedNumber(Number(degrees)), unitBesideValue(view)), plainModeName(form.mode));
}

// The value that switches the slope limit off, and the engine's automatic score smoothing as a multiple of the voxel size, as the
// descriptions of max_slope_deg and score_smoothing in GET schema state them (test_local_web_packaging.py checks they still do).
const SLOPE_LIMIT_OFF_IN_DESCRIPTION = /(\d+(?:\.\d+)?): off\b/;
const AUTOMATIC_SMOOTHING_IN_DESCRIPTION = /auto: (\d+(?:\.\d+)?) × voxel_size/;

/**
 * What the engine does with an empty setting in the form's mode, where the schema says it, else null: the number (where an empty
 * slider starts its handle, so a first key step moves from the value in use) and how it is said ("75 °", or "off" for the slope
 * limit of Solar time-based and the angle rule, which 90 switches off, as the tooltip says). The slope limit of the weighted modes;
 * the score smoothing, a multiple of the voxel size.
 */
export function automaticValueOf(view: SettingView, form: FormState): AutomaticValue | null {
  const description = form.schemaProperties[view.name]?.description ?? "";
  const numberIn = (pattern: RegExp) => {
    const found = pattern.exec(description)?.[1];
    return found === undefined ? null : Number(found);
  };
  const said = (value: number | null, text?: string) => (value === null ? null : { value, text: text ?? spokenValue(value, unitBesideValue(view)) });
  if (view.name === "max_slope_deg") {
    return form.scoreKindByMode[form.mode] === "weighted_sum" ? said(numberIn(AUTOMATIC_SLOPE_LIMIT_IN_DESCRIPTION))
      : said(numberIn(SLOPE_LIMIT_OFF_IN_DESCRIPTION), messages.switchedOff);
  }
  if (view.name === "score_smoothing") {
    const factor = numberIn(AUTOMATIC_SMOOTHING_IN_DESCRIPTION), voxelSize = shownValue(form, "voxel_size");
    return said(factor === null || typeof voxelSize !== "number" ? null : Number((factor * voxelSize).toPrecision(12)));
  }
  return null;
}

/** The default as the tooltip writes it ("1.0 m", "on", "21 Dec, 10 to 14 h", "automatic"). */
export function defaultTextOf(view: SettingView, form: FormState, isShadowTolerated: boolean): string {
  const unit = unitBesideValue(view);
  if (view.widget === "analysis_period") {
    const period = ANALYSIS_PERIOD_FIELDS.map((name) => defaultValue(form, name));
    return period.every((value) => typeof value === "number") ? messages.periodSummary(...(period as [number, number, number, number, number, number]))
      : messages.automatic;
  }
  const value = toDisplayValue(view.name, defaultValue(form, view.name), shownValue(form, "voxel_size"));
  if (view.widget === "threshold" && value === null) return isShadowTolerated ? withUnit("0", unit) : messages.carvingRuleChoices.carve_fraction;
  if (value === null) return messages.automatic;
  if (typeof value === "boolean") return value ? messages.switchedOn : messages.switchedOff;
  if (typeof value === "string") return CHOICE_NAMES[view.name]?.[value] ?? value;
  if (Array.isArray(value)) return withUnit(value.join(", "), unit);
  // A decimal setting reads like the engine's own default (1.0, not 1); a whole-number one stays whole.
  const isDecimalSetting = typesOf(form.schemaProperties[view.name]).includes("number") && view.display === undefined;
  return withUnit(typeof value === "number" && isDecimalSetting && Number.isInteger(value) ? value.toFixed(1) : String(value), unit);
}

export function WarningIcon() {
  return (
    <svg className="setting-error-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 1.5 15 14H1z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M8 6v4M8 11.5v1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function SettingField({ view, form, onChange, disabled = false, extras }: SettingFieldProps) {
  const inputId = useId();
  const labelId = `${inputId}-label`;
  const errorId = `${inputId}-error`;
  // A number refused in the field itself (out of range) is said under it, in place of the last save's message: it is newer.
  const [refusedInput, setRefusedInput] = useState<string | null>(null);
  const error = refusedInput ?? fieldErrorOf(form, view);
  const control: ControlProps = { inputId, labelId, invalid: error !== undefined, describedBy: error === undefined ? undefined : errorId, disabled,
                                  onRefusedInput: setRefusedInput };
  const property = form.schemaProperties[view.name];
  const types = typesOf(property);
  const unit = unitBesideValue(view);
  const isShadowTolerated = thresholdIsShadowToleratedIn(form.mode);
  const voxelSize = shownValue(form, "voxel_size");
  const shown = toDisplayValue(view.name, shownValue(form, view.name), voxelSize);
  const changeTo = (value: unknown) => onChange({ [view.name]: fromDisplayValue(view.name, value, voxelSize) });
  // Controls made of several inputs are labelled as a group; the others are the target of their label.
  const isGroupOfInputs = view.widget === "analysis_period" || view.widget === "tilted_plane_angles" || view.widget === "mesh_format"
    || view.widget === "balance_temperature";

  let controlElement: ReactNode;
  switch (view.widget) {
    case "analysis_period":
      controlElement = (
        <AnalysisPeriod {...control} onChange={onChange} coldPeriod={extras?.coldPeriod ?? null} hemisphere={extras?.hemisphere}
                        values={Object.fromEntries(ANALYSIS_PERIOD_FIELDS.map((name) => [name, shownValue(form, name)])) as Record<AnalysisPeriodField, number | null>} />
      );
      break;
    case "threshold":
      controlElement = <ThresholdRule {...control} value={shown as ThresholdSpec | null} isShadowTolerated={isShadowTolerated} unit={unit} onThreshold={changeTo} />;
      break;
    case "tilted_plane_angles":
      controlElement = (
        <TiltedPlaneAngles {...control} value={shown as number | number[] | null} unit={unit} onAngles={changeTo}
                           startingAngle={typeof defaultValue(form, view.name) === "number" ? (defaultValue(form, view.name) as number) : null} />
      );
      break;
    case "sun_steps_per_hour":
      controlElement = <SunStepsPerHour {...control} value={shown as number | null} onSteps={changeTo} />;
      break;
    case "mesh_format":
      controlElement = <MeshFormat {...control} value={shown as string | null} onFormat={changeTo} />;
      break;
    case "balance_temperature": {
      const [, deadBandName] = BALANCE_TEMPERATURE_FIELDS;
      const deadBand = shownValue(form, deadBandName);
      controlElement = (
        <BalanceTemperatureSlider {...control} balanceTemperature={typeof shown === "number" ? shown : null}
                                  deadBand={typeof deadBand === "number" ? deadBand : null}
                                  track={view.slider!} unit={unit} onChange={onChange}
                                  invalid={control.invalid || BALANCE_TEMPERATURE_FIELDS.some((name) => form.fieldErrors[name] !== undefined)} />
      );
      break;
    }
    default:
      if (types.includes("boolean")) {
        controlElement = (
          <input id={inputId} type="checkbox" role="switch" className="setting-switch" checked={shown === true} disabled={disabled}
                 aria-invalid={control.invalid} aria-describedby={control.describedBy} onChange={(event) => changeTo(event.target.checked)} />
        );
      } else if (property?.enum) {
        controlElement = (
          <select id={inputId} className="setting-select" value={String(shown ?? "")} disabled={disabled} aria-invalid={control.invalid}
                  aria-describedby={control.describedBy} onChange={(event) => changeTo(event.target.value)}>
            {property.enum.map((option) => (
              <option key={String(option)} value={String(option)}>{CHOICE_NAMES[view.name]?.[String(option)] ?? String(option)}</option>
            ))}
          </select>
        );
      } else {
        // The engine's bounds, from GET schema; a share shown in percent is held to 0 to 100.
        const engineRange = view.display === "percent" ? { minimum: 0, maximum: 100 } : rangeOf(property);
        const value = typeof shown === "number" ? shown : null;
        const mayBeEmpty = types.includes("null");
        const placeholder = mayBeEmpty && defaultValue(form, view.name) === null ? messages.automatic : undefined;
        const slider = shownSliderOf(view);
        controlElement = slider !== undefined ? (
          <RangeSlider {...control} value={value} slider={slider} engineRange={engineRange} mayBeEmpty={mayBeEmpty} unit={unit} placeholder={placeholder}
                       automatic={value === null ? automaticValueOf(view, form) : null} onValue={changeTo} />
        ) : (
          <div className="setting-control">
            <NumberInput id={inputId} value={value} mayBeEmpty={mayBeEmpty} wholeNumbers={types.includes("integer") && view.display === undefined}
                         invalid={control.invalid}
                         describedBy={control.describedBy} disabled={disabled} {...engineRange} onValue={changeTo} onRefused={setRefusedInput}
                         placeholder={placeholder} />
            {unit && <span className="setting-unit">{unit}</span>}
          </div>
        );
      }
  }

  return (
    // data-input-id names the input the label targets (a group's first), which a link to the setting focuses.
    <div className="setting-field" data-setting={view.name} data-input-id={inputId}>
      <div className="setting-label-row">
        {isGroupOfInputs ? <span id={labelId} className="setting-label">{view.label}</span>
          : <label id={labelId} htmlFor={inputId} className="setting-label">{view.label}</label>}
        <SettingTooltip settingLabel={view.label} help={view.help} defaultText={defaultTextOf(view, form, isShadowTolerated)}
                        configName={view.widget === "analysis_period" ? messages.analysisPeriodConfigNames : view.name}
                        extraLine={(view.name === "voxel_size" ? gridLineOf(form) : emptyMeaningOf(view, form)) ?? undefined} />
      </div>
      {controlElement}
      {error !== undefined && <p id={errorId} className="setting-error"><WarningIcon /><span>{refusedInput ?? extras?.errorContent ?? error}</span></p>}
      {extras?.notes?.map((note, index) => <p key={index} className="setting-note">{note}</p>)}
    </div>
  );
}
