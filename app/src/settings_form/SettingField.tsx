// One setting in the form (UX 7, 11): its plain label with the "i" of its tooltip, the control with the unit beside the value,
// and, after a rejected save, the message under it with a warning icon and the field outlined in the error colour.
import { useId, useState, type ReactNode } from "react";
import { messages } from "../messages";
import { withUnit } from "../steps/format_numbers";
import { plainModeName } from "../steps/step_summaries";
import { defaultValue, shownValue, type FormState, type SchemaProperty } from "./form_state";
import {
  ANALYSIS_PERIOD_FIELDS, fromDisplayValue, thresholdIsShadowToleratedIn, toDisplayValue, unitBesideValue, unitOfValue, type SettingView,
} from "./presentation";
import { SettingTooltip } from "./SettingTooltip";
import { AnalysisPeriod, type AnalysisPeriodField } from "./widgets/AnalysisPeriod";
import { MeshFormat } from "./widgets/MeshFormat";
import { NumberInput, type ControlProps, type NumberRange } from "./widgets/NumberInput";
import { PercentSlider } from "./widgets/PercentSlider";
import { SunStepsPerHour } from "./widgets/SunStepsPerHour";
import { ThresholdRule, type ThresholdSpec } from "./widgets/ThresholdRule";
import { TiltedPlaneAngles } from "./widgets/TiltedPlaneAngles";
import "./settings_form.css";

/** What a step adds under one of its fields: a note while the field is valid (the grid under Voxel size), and the error
 *  in the step's own words in place of the engine's message (the grid over the budget). */
export interface SettingFieldExtras {
  note?: ReactNode;
  errorContent?: ReactNode;
}

export interface SettingFieldProps {
  view: SettingView;
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  disabled?: boolean;
  extras?: SettingFieldExtras;
}

// The words shown for the options of a choice the engine names in code.
const CHOICE_NAMES: Record<string, Record<string, string>> = { plate_stacking: messages.floorStackingChoices };

/** The settings a view stands for: the six period settings for the analysis period, else its own. */
function settingNamesOf(view: SettingView): readonly string[] {
  return view.widget === "analysis_period" ? ANALYSIS_PERIOD_FIELDS : [view.name];
}

/** The messages of the last rejected save for the settings of *view*, or undefined. */
export function fieldErrorOf(form: FormState, view: SettingView): string | undefined {
  const errors = settingNamesOf(view).map((name) => form.fieldErrors[name]).filter((error) => error !== undefined);
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

// The engine's automatic slope limit (resolve_max_slope_deg): 75° in the weighted modes, off in the others.
const AUTOMATIC_SLOPE_LIMIT_DEGREES = 75;

/**
 * What an empty setting does in the form's mode, for a setting whose empty value the engine fills by mode, or null. The slope
 * limit is the one: 75° in the weighted modes, off in Sun at set hours and the angle rule. (Score smoothing says it in its help.)
 */
export function emptyMeaningOf(view: SettingView, form: Pick<FormState, "mode" | "scoreKindByMode">): string | null {
  if (view.name !== "max_slope_deg") return null;
  const valueText = form.scoreKindByMode[form.mode] === "weighted_sum" ? withUnit(String(AUTOMATIC_SLOPE_LIMIT_DEGREES), unitOfValue(view)) : messages.switchedOff;
  return messages.emptyMeansInMode(valueText, plainModeName(form.mode));
}

/** The default as the tooltip writes it ("1.0 m", "on", "21 Dec 10 h to 21 Dec 14 h", "automatic"). */
export function defaultTextOf(view: SettingView, form: FormState, isShadowTolerated: boolean): string {
  const unit = unitOfValue(view);
  if (view.widget === "analysis_period") {
    const period = ANALYSIS_PERIOD_FIELDS.map((name) => defaultValue(form, name));
    return period.every((value) => typeof value === "number") ? messages.periodText(...(period as [number, number, number, number, number, number]))
      : messages.automatic;
  }
  const value = toDisplayValue(view.name, defaultValue(form, view.name));
  if (view.widget === "threshold" && value === null) return isShadowTolerated ? withUnit("0", unit) : messages.carvingRuleChoices.carve_fraction;
  if (value === null) return messages.automatic;
  if (typeof value === "boolean") return value ? messages.switchedOn : messages.switchedOff;
  if (typeof value === "string") return CHOICE_NAMES[view.name]?.[value] ?? value;
  if (Array.isArray(value)) return withUnit(value.join(", "), unit);
  // A decimal setting reads like the engine's own default (1.0, not 1); a whole-number one stays whole.
  const isDecimalSetting = typesOf(form.schemaProperties[view.name]).includes("number") && view.display !== "percent";
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
  const shown = toDisplayValue(view.name, shownValue(form, view.name));
  const changeTo = (value: unknown) => onChange({ [view.name]: fromDisplayValue(view.name, value) });
  // Controls made of several inputs are labelled as a group; the others are the target of their label.
  const isGroupOfInputs = view.widget === "analysis_period" || view.widget === "tilted_plane_angles" || view.widget === "mesh_format";

  let controlElement: ReactNode;
  switch (view.widget) {
    case "analysis_period":
      controlElement = (
        <AnalysisPeriod {...control} onChange={onChange}
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
    case "percent_slider":
      controlElement = <PercentSlider {...control} percent={shown as number | null} unit={unit} onPercent={changeTo} />;
      break;
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
        const range = rangeOf(property);
        const isPercent = view.display === "percent";
        controlElement = (
          <div className="setting-control">
            <NumberInput id={inputId} value={typeof shown === "number" ? shown : null} mayBeEmpty={types.includes("null")}
                         wholeNumbers={types.includes("integer")} invalid={control.invalid} describedBy={control.describedBy} disabled={disabled}
                         {...(isPercent ? { minimum: 0, maximum: 100 } : range)} onValue={changeTo} onRefused={setRefusedInput}
                         placeholder={types.includes("null") && defaultValue(form, view.name) === null ? messages.automatic : undefined} />
            {unit && <span className="setting-unit">{unit}</span>}
          </div>
        );
      }
  }

  return (
    <div className="setting-field" data-setting={view.name}>
      <div className="setting-label-row">
        {isGroupOfInputs ? <span id={labelId} className="setting-label">{view.label}</span>
          : <label id={labelId} htmlFor={inputId} className="setting-label">{view.label}</label>}
        <SettingTooltip settingLabel={view.label} help={view.help} defaultText={defaultTextOf(view, form, isShadowTolerated)}
                        configName={view.widget === "analysis_period" ? messages.analysisPeriodConfigNames : view.name}
                        extraLine={view.name === "voxel_size" && form.gridPlan ? messages.gridSize(form.gridPlan.resolution, form.gridPlan.total_voxels)
                          : (emptyMeaningOf(view, form) ?? undefined)} />
      </div>
      {controlElement}
      {error !== undefined && <p id={errorId} className="setting-error"><WarningIcon /><span>{refusedInput ?? extras?.errorContent ?? error}</span></p>}
      {error === undefined && extras?.note !== undefined && <p className="setting-note">{extras.note}</p>}
    </div>
  );
}
