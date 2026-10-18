// A share shown in percent (UX 5.5): a slider from 0 to 100 with a number field beside it. Values here are the percent shown;
// SettingField converts them from and to the 0 to 1 the engine stores.
import { NumberInput, type ControlProps } from "./NumberInput";

interface PercentSliderProps extends ControlProps {
  percent: number | null;
  unit: string;
  onPercent: (percent: number) => void;
}

export function PercentSlider({ percent, unit, onPercent, inputId, labelId, invalid, describedBy, disabled, onRefusedInput }: PercentSliderProps) {
  return (
    <div className="setting-control setting-percent-slider">
      <input type="range" className="setting-range" min={0} max={100} step={1} value={percent ?? 0} aria-labelledby={labelId}
             aria-describedby={describedBy} disabled={disabled} onChange={(event) => onPercent(Number(event.target.value))} />
      <NumberInput id={inputId} className="setting-number setting-number-short" value={percent} mayBeEmpty={false} minimum={0} maximum={100}
                   invalid={invalid} describedBy={describedBy} disabled={disabled} onValue={(typed) => onPercent(typed!)} onRefused={onRefusedInput} />
      <span className="setting-unit">{unit}</span>
    </div>
  );
}
