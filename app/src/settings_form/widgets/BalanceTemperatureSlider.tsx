// The balance temperature of Solar usefulness: one track from 10 to 30 °C with two handles that set the two ends of the dead
// band, as the engine reads them. Hours colder than the lower end count (sun then saves heating); hours warmer than the upper end
// are the warm hours that count against the sun when harm is counted (include_harm), so without it the upper end is muted, with a
// note. The engine's settings are the middle and half the width: balance_temperature = (lower + upper) / 2, balance_offset =
// (upper - lower) / 2, so the lower end is balance_temperature - balance_offset and the upper end balance_temperature +
// balance_offset.
//
// Each handle moves its own end and cannot pass the other. Where the two lie on one spot (a dead band of 0, or both pinned at an
// end of the track), the direction of the move picks the handle: to the left the lower end, to the right the upper end. A drag
// keeps the handle its first move picked, to the pointer. A key toward the other end moves the focus to that end's handle and the
// browser steps it (stepUp, stepDown; Home and End take it to the track's end); the keys after it go to that handle. Both ends are number fields too, which take any
// temperature: a value off the track pins its handle at the track's end, and the handle says the value itself. A typed end past
// the other one closes the band there.
import { useId, useRef, type CSSProperties, type KeyboardEvent } from "react";
import { messages } from "../../messages";
import type { BALANCE_TEMPERATURE_FIELDS, SliderRange } from "../presentation";
import { NumberInput, type ControlProps } from "./NumberInput";
import { positionOnTrack, sliderValue, spokenValue } from "./RangeSlider";

export type BalanceTemperatureField = (typeof BALANCE_TEMPERATURE_FIELDS)[number];

interface BalanceTemperatureSliderProps extends ControlProps {
  balanceTemperature: number | null;
  deadBand: number | null;
  /** Whether warm hours count against the sun (include_harm): only then does the upper end do anything. */
  harmCounted: boolean;
  /** The track, in °C, and the step of both handles. */
  track: SliderRange;
  /** Whether the last save of either setting was refused: both ends show it, as each end is made of both settings. */
  invalid: boolean;
  unit: string;
  onChange: (values: Partial<Record<BalanceTemperatureField, number>>) => void;
}

// 15 - 13.1 is 1.9000000000000004 in floating point; twelve significant digits drop that noise and keep every real digit.
export const withoutFloatingPointNoise = (value: number) => Number(value.toPrecision(12));

/** The engine's two settings for a dead band from *lower* to *upper*. */
export function balanceSettingsOf(lower: number, upper: number): Record<BalanceTemperatureField, number> {
  return { balance_temperature: withoutFloatingPointNoise((lower + upper) / 2), balance_offset: withoutFloatingPointNoise((upper - lower) / 2) };
}

type End = "lower" | "upper";

// The keys that move a range input, and the end each moves toward: up, right and End the upper end, down, left and Home the
// lower end.
const END_OF_KEY: Record<string, End> = {
  ArrowRight: "upper", ArrowUp: "upper", PageUp: "upper", End: "upper", ArrowLeft: "lower", ArrowDown: "lower", PageDown: "lower", Home: "lower",
};

export function BalanceTemperatureSlider({ balanceTemperature, deadBand, harmCounted, track, invalid, unit, onChange, inputId, labelId, describedBy,
                                           disabled, onRefusedInput }: BalanceTemperatureSliderProps) {
  const balance = balanceTemperature ?? track.low, halfWidth = deadBand ?? 0;
  const lower = withoutFloatingPointNoise(balance - halfWidth), upper = withoutFloatingPointNoise(balance + halfWidth);
  const lowerOnTrack = positionOnTrack(lower, track), upperOnTrack = positionOnTrack(upper, track);
  const fractionOf = (position: number) => (position - track.low) / (track.high - track.low);
  // Where the band runs on the track, as fractions of it, for the stylesheet to place it under the handles' centres.
  const bandStyle = { "--dead-band-start": fractionOf(lowerOnTrack), "--dead-band-end": fractionOf(upperOnTrack) } as CSSProperties;
  const onOneSpot = lowerOnTrack >= upperOnTrack;
  const upperNoteId = useId();
  const describedWith = (...ids: (string | undefined)[]) => ids.filter((id) => id !== undefined).join(" ") || undefined;
  const upperDescribedBy = harmCounted ? describedBy : describedWith(describedBy, upperNoteId);

  const setEnd = (end: End, value: number) =>
    onChange(end === "lower" ? balanceSettingsOf(Math.min(value, upper), upper) : balanceSettingsOf(lower, Math.max(value, lower)));

  // The end a drag moves, from the press to the release: on one spot its first move picks it by its direction. Null between drags.
  const endDragged = useRef<End | "undecided" | null>(null);
  const moveHandle = (own: End, text: string) => {
    let end = endDragged.current ?? (onOneSpot ? "undecided" : own);
    if (end === "undecided") {
      end = Number(text) > lowerOnTrack ? "upper" : "lower";
      if (endDragged.current === "undecided") endDragged.current = end;
    }
    setEnd(end, sliderValue(text, track));
  };
  const handleInputs = useRef<Partial<Record<End, HTMLInputElement | null>>>({});
  const onKeyDown = (own: End, event: KeyboardEvent<HTMLInputElement>) => {
    const end = END_OF_KEY[event.key];
    if (!onOneSpot || end === undefined || end === own) return;    // the browser moves the focused handle
    const other = handleInputs.current[end];
    if (!other) return;
    event.preventDefault();
    other.focus();
    if (event.key === "Home" || event.key === "End") other.value = String(end === "upper" ? track.high : track.low);
    else if (end === "upper") other.stepUp();
    else other.stepDown();
    setEnd(end, sliderValue(other.value, track));
  };
  const handleProps = (own: End) => ({
    ref: (element: HTMLInputElement | null) => { handleInputs.current[own] = element; },
    min: track.low, max: track.high, step: track.step, "aria-invalid": invalid, disabled,
    "aria-describedby": own === "upper" ? upperDescribedBy : describedBy,
    onPointerDown: () => { if (endDragged.current === null) endDragged.current = onOneSpot ? "undecided" : own; },
    onPointerUp: () => { endDragged.current = null; }, onBlur: () => { endDragged.current = null; },
    onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => onKeyDown(own, event),
    onChange: (event: { target: { value: string } }) => moveHandle(own, event.target.value),
  });

  // Each number field keeps its own refusal; the field shows the one standing.
  const refusals = useRef<Partial<Record<End, string | null>>>({});
  const refusedIn = (end: End) => (refusal: string | null) => {
    refusals.current = { ...refusals.current, [end]: refusal };
    onRefusedInput?.(refusals.current.lower ?? refusals.current.upper ?? null);
  };
  const typed = (end: End) => (value: number | null) => {
    if (value === null) return;
    onChange(end === "lower" ? balanceSettingsOf(value, Math.max(value, upper)) : balanceSettingsOf(Math.min(value, lower), value));
  };
  const upperMuted = harmCounted ? "" : " balance-handle-muted";
  return (
    <div role="group" aria-labelledby={labelId} className="balance-slider">
      <div className="balance-track" style={bandStyle}>
        <span className="balance-dead-band" aria-hidden="true" />
        {/* No band to name where the handles lie on one spot. */}
        {!onOneSpot && <span className="balance-dead-band-label" aria-hidden="true">{messages.deadBandOnTrack}</span>}
        {/* The lower end first, as on the track and in the number fields, so Tab reaches the ends in their order; on one spot it is
            drawn on top (balance-handle-on-top), and a key toward the upper end moves the focus there. */}
        <input type="range" className={onOneSpot ? "balance-handle balance-handle-on-top" : "balance-handle"} {...handleProps("lower")}
               value={lowerOnTrack} aria-label={messages.balanceLowerEnd} aria-valuetext={spokenValue(lower, unit)} />
        <input type="range" className={`balance-handle${upperMuted}`} {...handleProps("upper")} value={upperOnTrack}
               aria-label={messages.balanceUpperEnd} aria-valuetext={spokenValue(upper, unit)} />
      </div>
      <div className="balance-numbers">
        {([["lower", lower, messages.balanceLowerEnd, inputId], ["upper", upper, messages.balanceUpperEnd, undefined]] as const).map(([end, value, name, id]) => (
          <span key={end} className={end === "upper" && !harmCounted ? "setting-control balance-end-muted" : "setting-control"}>
            <span className="setting-label">{name}</span>
            <NumberInput id={id} className="setting-number setting-number-short" ariaLabel={name} value={balanceTemperature === null ? null : value}
                         mayBeEmpty={false} invalid={invalid} describedBy={end === "upper" ? upperDescribedBy : describedBy} disabled={disabled}
                         onValue={typed(end)} onRefused={refusedIn(end)} />
            <span className="setting-unit">{unit}</span>
            {end === "upper" && !harmCounted && <span id={upperNoteId} className="balance-end-note">{messages.balanceUpperEndWithoutHarm}</span>}
          </span>
        ))}
      </div>
    </div>
  );
}
