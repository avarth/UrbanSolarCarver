// The balance temperature of Solar usefulness: one track from 10 to 30 °C with two handles that set the two ends of the dead
// band, as the engine reads them. Hours colder than the lower end count (sun then saves heating); hours warmer than the upper end
// are the warm hours that count against the sun when harm is counted (include_harm). The engine's settings are the middle and half
// the width: balance_temperature = (lower + upper) / 2, balance_offset = (upper - lower) / 2, so the lower end is
// balance_temperature - balance_offset and the upper end balance_temperature + balance_offset.
//
// Each handle moves its own end and cannot pass the other. Where the two lie on one spot (a dead band of 0, or both pinned at an
// end of the track), the direction of the move picks the handle: to the left the lower end, to the right the upper end; a drag,
// or a run of keys until the handle loses the focus, keeps the handle its first move picked. A key moves the picked end one step
// from where that end is drawn (the browser steps the focused handle, which may be the other end's), a drag to the pointer. Both ends are number fields too, which
// take any temperature: a value off the track pins its handle at the track's end, and the handle says the value itself. A typed
// end past the other one closes the band there.
import { useRef, type CSSProperties } from "react";
import { messages } from "../../messages";
import type { BALANCE_TEMPERATURE_FIELDS, SliderRange } from "../presentation";
import { NumberInput, type ControlProps } from "./NumberInput";
import { positionOnTrack, sliderValue, spokenValue } from "./RangeSlider";

export type BalanceTemperatureField = (typeof BALANCE_TEMPERATURE_FIELDS)[number];

interface BalanceTemperatureSliderProps extends ControlProps {
  balanceTemperature: number | null;
  deadBand: number | null;
  /** The track, in °C, and the step of both handles. */
  track: SliderRange;
  /** Whether the last save of either setting was refused: both ends show it, as each end is made of both settings. */
  invalid: boolean;
  unit: string;
  onChange: (values: Partial<Record<BalanceTemperatureField, number>>) => void;
}

// 15 - 13.1 is 1.9000000000000004 in floating point; twelve significant digits drop that noise and keep every real digit.
const withoutFloatingPointNoise = (value: number) => Number(value.toPrecision(12));

/** The engine's two settings for a dead band from *lower* to *upper*. */
export function balanceSettingsOf(lower: number, upper: number): Record<BalanceTemperatureField, number> {
  return { balance_temperature: withoutFloatingPointNoise((lower + upper) / 2), balance_offset: withoutFloatingPointNoise((upper - lower) / 2) };
}

type End = "lower" | "upper";

export function BalanceTemperatureSlider({ balanceTemperature, deadBand, track, invalid, unit, onChange, inputId, labelId, describedBy, disabled,
                                           onRefusedInput }: BalanceTemperatureSliderProps) {
  const balance = balanceTemperature ?? track.low, halfWidth = deadBand ?? 0;
  const lower = withoutFloatingPointNoise(balance - halfWidth), upper = withoutFloatingPointNoise(balance + halfWidth);
  const lowerOnTrack = positionOnTrack(lower, track), upperOnTrack = positionOnTrack(upper, track);
  const fractionOf = (position: number) => (position - track.low) / (track.high - track.low);
  // Where the band runs on the track, as fractions of it, for the stylesheet to place it under the handles' centres.
  const bandStyle = { "--dead-band-start": fractionOf(lowerOnTrack), "--dead-band-end": fractionOf(upperOnTrack) } as CSSProperties;
  const onOneSpot = lowerOnTrack >= upperOnTrack;

  // The end a handle moves for a drag, from the press to the release, and for a run of keys, from the first key until the handle
  // loses the focus: on one spot the first move picks it by its direction. Null between them.
  const endMoved = useRef<End | "undecided" | null>(null);
  const byKeys = useRef(false);
  const startMove = (own: End, withKeys: boolean) => {
    if (endMoved.current !== null) return;
    endMoved.current = onOneSpot ? "undecided" : own;
    byKeys.current = withKeys;
  };
  const stopMove = () => { endMoved.current = null; };
  const onTrackOf = (end: End) => (end === "lower" ? lowerOnTrack : upperOnTrack);
  const moveHandle = (own: End, text: string) => {
    let end = endMoved.current === null ? (onOneSpot ? "undecided" : own) : endMoved.current;
    if (end === "undecided") {
      end = Number(text) > lowerOnTrack ? "upper" : "lower";
      if (endMoved.current === "undecided") endMoved.current = end;
    }
    const position = byKeys.current && end !== own ? String(onTrackOf(end) + Number(text) - onTrackOf(own)) : text;
    const value = sliderValue(position, track);
    onChange(end === "lower" ? balanceSettingsOf(Math.min(value, upper), upper) : balanceSettingsOf(lower, Math.max(value, lower)));
  };
  const handleProps = (own: End) => ({
    min: track.low, max: track.high, step: track.step, "aria-describedby": describedBy, "aria-invalid": invalid, disabled,
    onPointerDown: () => startMove(own, false), onPointerUp: stopMove, onBlur: stopMove, onKeyDown: () => startMove(own, true),
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
  return (
    <div role="group" aria-labelledby={labelId} className="balance-slider">
      <div className="balance-track" style={bandStyle}>
        <span className="balance-dead-band" aria-hidden="true" />
        {/* No band to name where the handles lie on one spot. */}
        {!onOneSpot && <span className="balance-dead-band-label" aria-hidden="true">{messages.deadBandOnTrack}</span>}
        {/* The lower end is drawn last, so it is on top where the two lie on one spot (the direction then picks the end). */}
        <input type="range" className="balance-handle" {...handleProps("upper")} value={upperOnTrack}
               aria-label={messages.balanceUpperEnd} aria-valuetext={spokenValue(upper, unit)} />
        <input type="range" className={onOneSpot ? "balance-handle balance-handle-on-top" : "balance-handle"} {...handleProps("lower")}
               value={lowerOnTrack} aria-label={messages.balanceLowerEnd} aria-valuetext={spokenValue(lower, unit)} />
      </div>
      <div className="balance-numbers">
        {([["lower", lower, messages.balanceLowerEnd, inputId], ["upper", upper, messages.balanceUpperEnd, undefined]] as const).map(([end, value, name, id]) => (
          <span key={end} className="setting-control">
            <span className="setting-label">{name}</span>
            <NumberInput id={id} className="setting-number setting-number-short" ariaLabel={name} value={balanceTemperature === null ? null : value}
                         mayBeEmpty={false} invalid={invalid} describedBy={describedBy} disabled={disabled} onValue={typed(end)}
                         onRefused={refusedIn(end)} />
            <span className="setting-unit">{unit}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
