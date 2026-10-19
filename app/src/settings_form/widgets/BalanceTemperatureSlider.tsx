// The balance temperature of Solar usefulness: one strip from 10 to 30 °C, drawn as the strips of the analysis period are
// (ScaleStrip), with two handles that set the two ends of the dead band, as the engine reads them, and the band between them
// filled. Each handle shows its exact value in a bubble over it ("14.5 °C"). Hours colder than the lower end count (sun then saves
// heating); hours warmer than the upper end are the warm hours that count against the sun when harm is counted (include_harm), so
// without it the upper end is muted, with a note under it that also describes its handle. The engine's settings are the middle
// and half the width: balance_temperature = (lower + upper) / 2, balance_offset = (upper - lower) / 2, so the lower end is
// balance_temperature - balance_offset and the upper end balance_temperature + balance_offset.
//
// Each handle moves its own end and cannot pass the other. Where the two lie on one spot (a dead band of 0, or both pinned at an
// end of the strip), the direction of the move picks the handle: to the left the lower end, to the right the upper end. A drag
// keeps the handle its first move picked. A key toward the other end moves the focus to that end's handle and steps it (Home and
// End take it to the strip's end); the keys after it go to that handle. A value off the strip (a hand-edited config) pins its
// handle at the strip's end, and its bubble and the handle say the value itself; a key steps it from the end it is drawn at.
import { messages } from "../../messages";
import type { BALANCE_TEMPERATURE_FIELDS, SliderRange } from "../presentation";
import type { ControlProps } from "./NumberInput";
import { positionOnTrack, sliderValue, spokenValue } from "./RangeSlider";
import { ScaleStrip, type ScaleStripCell } from "./ScaleStrip";

export type BalanceTemperatureField = (typeof BALANCE_TEMPERATURE_FIELDS)[number];

interface BalanceTemperatureSliderProps extends ControlProps {
  balanceTemperature: number | null;
  deadBand: number | null;
  /** Whether warm hours count against the sun (include_harm): only then does the upper end do anything. */
  harmCounted: boolean;
  /** The strip, in °C, and the step of both handles. */
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

// The keys that move an end, and the end each moves toward: up, right, Page Up and End the upper end; down, left, Page Down and
// Home the lower end.
const END_OF_KEY: Record<string, End> = {
  ArrowRight: "upper", ArrowUp: "upper", PageUp: "upper", End: "upper", ArrowLeft: "lower", ArrowDown: "lower", PageDown: "lower", Home: "lower",
};

// Page Up and Page Down move an end by a tenth of the strip: 2 °C on 10 to 30 °C.
const PAGES_PER_TRACK = 10;
// The scale labels a degree in this many (10, 15, 20, 25 °C), as the hour strip labels every 6 h.
const DEGREES_PER_SCALE_LABEL = 5;

/** Where a key takes an end that is drawn at *position* on the strip (a value off it steps from the end it is drawn at); null for a key that moves nothing. */
export function balanceEndAfterKey(position: number, key: string, track: SliderRange): number | null {
  const page = (track.high - track.low) / PAGES_PER_TRACK;
  const moves: Record<string, number> = {
    ArrowRight: position + track.step, ArrowUp: position + track.step, ArrowLeft: position - track.step, ArrowDown: position - track.step,
    PageUp: position + page, PageDown: position - page, Home: track.low, End: track.high,
  };
  return key in moves ? positionOnTrack(sliderValue(String(moves[key]), track), track) : null;
}

/** The temperature under the pointer, *fraction* of the way along the strip, to the step of the strip. */
function temperatureAt(fraction: number, track: SliderRange): number {
  const steps = Math.round((fraction * (track.high - track.low)) / track.step);
  return positionOnTrack(sliderValue(String(track.low + steps * track.step), track), track);
}

/** The scale: a cell a degree, labelled every 5 °C. */
function temperatureCells(track: SliderRange): ScaleStripCell[] {
  return Array.from({ length: Math.round(track.high - track.low) }, (_, index) => {
    const degree = track.low + index;
    return { label: degree % DEGREES_PER_SCALE_LABEL === 0 ? String(degree) : "", length: 1 };
  });
}

export function BalanceTemperatureSlider({ balanceTemperature, deadBand, harmCounted, track, invalid, unit, onChange, inputId, labelId, describedBy,
                                           disabled }: BalanceTemperatureSliderProps) {
  const balance = balanceTemperature ?? track.low, halfWidth = deadBand ?? 0;
  const lower = withoutFloatingPointNoise(balance - halfWidth), upper = withoutFloatingPointNoise(balance + halfWidth);
  const lowerOnTrack = positionOnTrack(lower, track), upperOnTrack = positionOnTrack(upper, track);
  const fractionOf = (position: number) => (position - track.low) / (track.high - track.low);
  const onOneSpot = lowerOnTrack >= upperOnTrack;

  // An end cannot pass the other; an end set where it already is sends nothing.
  const setEnd = (end: End, value: number) => {
    const [nextLower, nextUpper] = end === "lower" ? [Math.min(value, upper), upper] : [lower, Math.max(value, lower)];
    if (nextLower !== lower || nextUpper !== upper) onChange(balanceSettingsOf(nextLower, nextUpper));
  };
  // On one spot a key picks the end by its direction; elsewhere it moves the end of its own handle.
  const onKey = (own: End, key: string): End | null => {
    const towards = END_OF_KEY[key];
    if (towards === undefined) return null;
    const moved = onOneSpot ? towards : own;
    setEnd(moved, balanceEndAfterKey(moved === "lower" ? lowerOnTrack : upperOnTrack, key, track)!);
    return moved;
  };

  const upperMuted = !harmCounted;
  return (
    <div role="group" aria-labelledby={labelId} className="balance-slider">
      {/* The lower end first, as on the strip, so Tab reaches the ends in their order. */}
      <ScaleStrip<End>
        handles={[
          { name: "lower", id: inputId, position: fractionOf(lowerOnTrack), accessibleName: messages.balanceLowerEnd, valueNow: lowerOnTrack,
            spokenValue: spokenValue(lower, unit), bubbleText: spokenValue(lower, unit) },
          { name: "upper", position: fractionOf(upperOnTrack), accessibleName: messages.balanceUpperEnd, valueNow: upperOnTrack,
            spokenValue: spokenValue(upper, unit), bubbleText: spokenValue(upper, unit), muted: upperMuted,
            note: upperMuted ? messages.balanceUpperEndWithoutHarm : undefined },
        ]}
        segments={[{ start: fractionOf(lowerOnTrack), end: fractionOf(upperOnTrack) }]} cells={temperatureCells(track)}
        valueAt={(fraction) => temperatureAt(fraction, track)} valueRange={[track.low, track.high]} invalid={invalid} describedBy={describedBy}
        disabled={disabled} onDragMove={setEnd} onDragEnd={() => {}} onKey={onKey} />
    </div>
  );
}
