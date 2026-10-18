// A ranged number setting (R2 4.1): a slider over the range people normally use, with a number field beside it that takes any
// value the engine accepts. A value outside the slider's range pins the handle at the end of its track, and the slider still says
// the value itself to a screen reader. An empty value (automatic) shows a hollow handle at the value the engine uses when it is
// known, else in the middle of the track; the value stays empty until the slider is moved. Every move is passed on; the form saves
// once the moves stop (SAVE_DELAY_MILLISECONDS), so a drag is one save.
import { messages } from "../../messages";
import { formattedNumber, withUnit } from "../../steps/format_numbers";
import type { SliderRange } from "../presentation";
import { NumberInput, type ControlProps, type NumberRange } from "./NumberInput";

/** The number the engine uses for an empty setting, and how it is said ("75 °", "off"). */
export interface AutomaticValue {
  value: number;
  text: string;
}

interface RangeSliderProps extends ControlProps {
  value: number | null;
  /** The slider, in the units shown. */
  slider: SliderRange;
  /** The engine's bounds, which the number field holds to. */
  engineRange: NumberRange;
  mayBeEmpty: boolean;
  unit: string;
  /** What the empty number field shows ("automatic"); also what the slider says while the value is empty. */
  placeholder?: string;
  /** While the value is empty: what the engine uses for it, where known (the handle starts at its number), else null. */
  automatic?: AutomaticValue | null;
  onValue: (value: number | null) => void;
}

/** The number of decimals written in *value* (0.05 has 2). */
function decimalsIn(value: number): number {
  return String(value).split(".")[1]?.length ?? 0;
}

/** *value* on the track: at its nearest end when it lies outside. */
export function positionOnTrack(value: number, slider: SliderRange): number {
  return Math.min(Math.max(value, slider.low), slider.high);
}

/** A value from the slider, written with no more decimals than its low end and step have: 0.30000000000000004 is 0.3. */
export function sliderValue(text: string, slider: SliderRange): number {
  return Number(Number(text).toFixed(Math.max(decimalsIn(slider.low), decimalsIn(slider.step))));
}

/** What a slider says to a screen reader: the value with its unit, the one outside the track included. */
export function spokenValue(value: number, unit: string): string {
  return withUnit(formattedNumber(value), unit);
}

export function RangeSlider({ value, slider, engineRange, mayBeEmpty, unit, placeholder, automatic = null, onValue, inputId, labelId, invalid,
                              describedBy, disabled, onRefusedInput }: RangeSliderProps) {
  const isEmpty = value === null;
  const emptyPosition = automatic === null ? (slider.low + slider.high) / 2 : positionOnTrack(automatic.value, slider);
  const emptyText = automatic === null ? placeholder : messages.automaticValue(automatic.text);
  return (
    <div className="setting-control setting-slider-control">
      <input type="range" className="setting-range" min={slider.low} max={slider.high} step={slider.step}
             value={isEmpty ? emptyPosition : positionOnTrack(value, slider)} aria-labelledby={labelId} aria-describedby={describedBy}
             aria-invalid={invalid} aria-valuetext={isEmpty ? emptyText : spokenValue(value, unit)} data-empty={isEmpty ? "true" : undefined}
             disabled={disabled} onChange={(event) => onValue(sliderValue(event.target.value, slider))} />
      {/* Short beside the slider, but wide enough for its placeholder ("automatic") where it has one. */}
      <NumberInput id={inputId} className={placeholder === undefined ? "setting-number setting-number-short" : "setting-number"} value={value}
                   mayBeEmpty={mayBeEmpty} {...engineRange} invalid={invalid} describedBy={describedBy} disabled={disabled} placeholder={placeholder}
                   onValue={onValue} onRefused={onRefusedInput} />
      {unit && <span className="setting-unit">{unit}</span>}
    </div>
  );
}
