// The balance temperature of Solar usefulness (R2 4.2): one track from 10 to 30 °C with two handles. The right handle is the
// balance temperature; the left one is the balance temperature minus the dead band, so the band between them is the dead band.
// Moving the right handle moves the band with it (the dead band stays); moving the left one changes only the dead band, and it
// cannot pass the right one (the engine needs a dead band of 0 or more). Both values are number fields too, which take any value
// the engine accepts: a temperature off the track pins its handle at the track's end, and the handle says the value itself.
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
  /** How far one step of the left handle moves the lower end of the dead band. */
  deadBandStep: number;
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

export function BalanceTemperatureSlider({ balanceTemperature, deadBand, track, deadBandStep, balanceTemperatureRange, deadBandRange, unit, deadBandLabel,
                                           deadBandInfo, onChange, inputId, labelId, invalid, describedBy, disabled, onRefusedInput }: BalanceTemperatureSliderProps) {
  const balance = balanceTemperature ?? track.low;
  const lowerEnd = withoutFloatingPointNoise(balance - (deadBand ?? 0));
  const balanceOnTrack = positionOnTrack(balance, track), lowerEndOnTrack = positionOnTrack(lowerEnd, track);
  const fractionOf = (position: number) => (position - track.low) / (track.high - track.low);
  // Where the band runs on the track, as fractions of it, for the stylesheet to place it under the handles' centres.
  const bandStyle = { "--dead-band-start": fractionOf(lowerEndOnTrack), "--dead-band-end": fractionOf(balanceOnTrack) } as CSSProperties;
  // On one spot, the left handle lies over the right one, so a drag from there opens the band.
  const lowerEndClass = lowerEndOnTrack >= balanceOnTrack ? "balance-handle balance-handle-on-top" : "balance-handle";

  // Each number field keeps its own refusal; the field shows the one standing, so a valid temperature never hides a refused band.
  const refusals = useRef<Partial<Record<BalanceTemperatureField, string | null>>>({});
  const refusedIn = (field: BalanceTemperatureField) => (refusal: string | null) => {
    refusals.current = { ...refusals.current, [field]: refusal };
    onRefusedInput?.(refusals.current.balance_temperature ?? refusals.current.balance_offset ?? null);
  };
  const handleProps = { min: track.low, max: track.high, "aria-describedby": describedBy, "aria-invalid": invalid, disabled };
  return (
    <div role="group" aria-labelledby={labelId} className="balance-slider">
      <div className="balance-track" style={bandStyle}>
        <span className="balance-dead-band" aria-hidden="true" />
        <span className="balance-dead-band-label" aria-hidden="true">{messages.deadBandOnTrack}</span>
        <input type="range" className={lowerEndClass} {...handleProps} step={deadBandStep} value={lowerEndOnTrack}
               aria-label={messages.deadBandLowerEndHandle} aria-valuetext={spokenValue(lowerEnd, unit)}
               onChange={(event) => {
                 const moved = Math.min(sliderValue(event.target.value, { ...track, step: deadBandStep }), balance);
                 onChange({ balance_offset: withoutFloatingPointNoise(balance - moved) });
               }} />
        <input type="range" className="balance-handle" {...handleProps} step={track.step} value={balanceOnTrack}
               aria-label={messages.balanceTemperatureHandle} aria-valuetext={spokenValue(balance, unit)}
               onChange={(event) => onChange({ balance_temperature: sliderValue(event.target.value, track) })} />
      </div>
      <div className="balance-numbers">
        <span className="setting-control">
          <NumberInput id={inputId} className="setting-number setting-number-short" ariaLabel={messages.balanceTemperatureHandle} value={balanceTemperature}
                       mayBeEmpty={false} {...balanceTemperatureRange} invalid={invalid} describedBy={describedBy} disabled={disabled}
                       onValue={(typed) => onChange({ balance_temperature: typed! })} onRefused={refusedIn("balance_temperature")} />
          <span className="setting-unit">{unit}</span>
        </span>
        <span className="setting-control">
          <span className="setting-label-row">
            <span className="setting-label">{deadBandLabel}</span>
            {deadBandInfo}
          </span>
          <NumberInput className="setting-number setting-number-short" ariaLabel={deadBandLabel} value={deadBand} mayBeEmpty={false} {...deadBandRange}
                       invalid={invalid} describedBy={describedBy} disabled={disabled} onValue={(typed) => onChange({ balance_offset: typed! })}
                       onRefused={refusedIn("balance_offset")} />
          <span className="setting-unit">{unit}</span>
        </span>
      </div>
    </div>
  );
}
