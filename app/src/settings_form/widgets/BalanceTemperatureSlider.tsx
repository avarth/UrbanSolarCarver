// The balance temperature of Solar usefulness (R2 4.2): one track from 10 to 30 °C with two handles. The right handle is the
// balance temperature; the left one is the balance temperature minus the dead band, so the band between them is the dead band.
// Moving the right handle moves the band with it (the dead band stays); moving the left one changes only the dead band, and it
// cannot pass the right one (the engine needs a dead band of 0 or more). Where the two handles lie on one spot (a dead band of 0,
// or both pinned at an end of the track), the left one is on top and the direction of the move picks the handle: to the right it
// moves the balance temperature with the band, to the left it opens the band; a drag keeps the handle its first move picked.
// Both values are number fields too, which take any value the engine accepts: a temperature off the track pins its handle at the
// track's end, and the handle says the value itself. A setting with an error marks only its own handle and number field.
import { useRef, type CSSProperties, type ReactNode } from "react";
import { messages } from "../../messages";
import type { BALANCE_TEMPERATURE_FIELDS, SliderRange } from "../presentation";
import { NumberInput, type ControlProps, type NumberRange } from "./NumberInput";
import { positionOnTrack, sliderValue, spokenValue } from "./RangeSlider";

export type BalanceTemperatureField = (typeof BALANCE_TEMPERATURE_FIELDS)[number];

interface BalanceTemperatureSliderProps extends ControlProps {
  balanceTemperature: number | null;
  deadBand: number | null;
  /** The track, in °C. */
  track: SliderRange;
  /** How far one step of the left handle moves the lower end of the dead band (the step of balance_offset's slider entry). */
  deadBandStep: number;
  /** The settings of the two whose last save was refused: each marks its own handle and number field. */
  settingsWithError: readonly string[];
  balanceTemperatureRange: NumberRange;
  deadBandRange: NumberRange;
  unit: string;
  deadBandLabel: string;
  /** The "i" of the dead band's tooltip, beside its label. */
  deadBandInfo: ReactNode;
  onChange: (values: Partial<Record<BalanceTemperatureField, number>>) => void;
}

// 15 - 13.1 is 1.9000000000000004 in floating point; twelve significant digits drop that noise and keep every real digit.
const withoutFloatingPointNoise = (value: number) => Number(value.toPrecision(12));

/** Which handle a move of the left (upper) handle moves: undecided until the first move of a drag that started on one spot. */
type HandleMoved = "balance_temperature" | "lower_end" | "undecided";

export function BalanceTemperatureSlider({ balanceTemperature, deadBand, track, deadBandStep, settingsWithError, balanceTemperatureRange, deadBandRange, unit,
                                           deadBandLabel, deadBandInfo, onChange, inputId, labelId, describedBy, disabled, onRefusedInput }: BalanceTemperatureSliderProps) {
  const balance = balanceTemperature ?? track.low;
  const lowerEnd = withoutFloatingPointNoise(balance - (deadBand ?? 0));
  const balanceOnTrack = positionOnTrack(balance, track), lowerEndOnTrack = positionOnTrack(lowerEnd, track);
  const fractionOf = (position: number) => (position - track.low) / (track.high - track.low);
  // Where the band runs on the track, as fractions of it, for the stylesheet to place it under the handles' centres.
  const bandStyle = { "--dead-band-start": fractionOf(lowerEndOnTrack), "--dead-band-end": fractionOf(balanceOnTrack) } as CSSProperties;
  const onOneSpot = lowerEndOnTrack >= balanceOnTrack;
  const lowerEndClass = onOneSpot ? "balance-handle balance-handle-on-top" : "balance-handle";
  // The handle a drag of the left handle moves, from the press to the release; null while no drag is under way (keys).
  const dragOfLeftHandle = useRef<HandleMoved | null>(null);
  const moveLeftHandle = (text: string) => {
    let handle = dragOfLeftHandle.current;
    if (handle === null || handle === "undecided") {
      handle = onOneSpot && Number(text) > lowerEndOnTrack ? "balance_temperature" : "lower_end";
      if (dragOfLeftHandle.current === "undecided") dragOfLeftHandle.current = handle;
    }
    if (handle === "balance_temperature") {
      onChange({ balance_temperature: sliderValue(text, track) });
      return;
    }
    const moved = Math.min(sliderValue(text, { ...track, step: deadBandStep }), balance);
    onChange({ balance_offset: withoutFloatingPointNoise(balance - moved) });
  };

  // Each number field keeps its own refusal; the field shows the one standing, so a valid temperature never hides a refused band.
  const refusals = useRef<Partial<Record<BalanceTemperatureField, string | null>>>({});
  const refusedIn = (field: BalanceTemperatureField) => (refusal: string | null) => {
    refusals.current = { ...refusals.current, [field]: refusal };
    onRefusedInput?.(refusals.current.balance_temperature ?? refusals.current.balance_offset ?? null);
  };
  const balanceInvalid = settingsWithError.includes("balance_temperature") || (refusals.current.balance_temperature ?? null) !== null;
  const deadBandInvalid = settingsWithError.includes("balance_offset") || (refusals.current.balance_offset ?? null) !== null;
  const handleProps = { min: track.low, max: track.high, "aria-describedby": describedBy, disabled };
  return (
    <div role="group" aria-labelledby={labelId} className="balance-slider">
      <div className="balance-track" style={bandStyle}>
        <span className="balance-dead-band" aria-hidden="true" />
        {/* No band to name where the handles lie on one spot. */}
        {!onOneSpot && <span className="balance-dead-band-label" aria-hidden="true">{messages.deadBandOnTrack}</span>}
        <input type="range" className={lowerEndClass} {...handleProps} aria-invalid={deadBandInvalid} step={deadBandStep} value={lowerEndOnTrack}
               aria-label={messages.deadBandLowerEndHandle} aria-valuetext={spokenValue(lowerEnd, unit)}
               onPointerDown={() => { dragOfLeftHandle.current = onOneSpot ? "undecided" : "lower_end"; }}
               onPointerUp={() => { dragOfLeftHandle.current = null; }} onBlur={() => { dragOfLeftHandle.current = null; }}
               onChange={(event) => moveLeftHandle(event.target.value)} />
        <input type="range" className="balance-handle" {...handleProps} aria-invalid={balanceInvalid} step={track.step} value={balanceOnTrack}
               aria-label={messages.balanceTemperatureHandle} aria-valuetext={spokenValue(balance, unit)}
               onChange={(event) => onChange({ balance_temperature: sliderValue(event.target.value, track) })} />
      </div>
      <div className="balance-numbers">
        <span className="setting-control">
          <NumberInput id={inputId} className="setting-number setting-number-short" ariaLabel={messages.balanceTemperatureHandle} value={balanceTemperature}
                       mayBeEmpty={false} {...balanceTemperatureRange} invalid={balanceInvalid} describedBy={describedBy} disabled={disabled}
                       onValue={(typed) => onChange({ balance_temperature: typed! })} onRefused={refusedIn("balance_temperature")} />
          <span className="setting-unit">{unit}</span>
        </span>
        <span className="setting-control">
          <span className="setting-label-row">
            <span className="setting-label">{deadBandLabel}</span>
            {deadBandInfo}
          </span>
          <NumberInput className="setting-number setting-number-short" ariaLabel={deadBandLabel} value={deadBand} mayBeEmpty={false} {...deadBandRange}
                       invalid={deadBandInvalid} describedBy={describedBy} disabled={disabled} onValue={(typed) => onChange({ balance_offset: typed! })}
                       onRefused={refusedIn("balance_offset")} />
          <span className="setting-unit">{unit}</span>
        </span>
      </div>
    </div>
  );
}
