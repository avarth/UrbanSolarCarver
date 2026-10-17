// Sun positions per hour (UX 7): a choice of the timesteps the engine accepts, each with the interval it gives.
import { messages } from "../../messages";
import type { ControlProps } from "./NumberInput";

// The Ladybug timesteps that the engine's config validation accepts for sun_steps_per_hour.
export const SUN_STEPS_PER_HOUR_CHOICES = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60];

interface SunStepsPerHourProps extends ControlProps {
  value: number | null;
  onSteps: (stepsPerHour: number) => void;
}

export function SunStepsPerHour({ value, onSteps, inputId, invalid, describedBy, disabled }: SunStepsPerHourProps) {
  return (
    <select id={inputId} className="setting-select" value={value ?? ""} aria-invalid={invalid} aria-describedby={describedBy} disabled={disabled}
            onChange={(event) => onSteps(Number(event.target.value))}>
      {SUN_STEPS_PER_HOUR_CHOICES.map((stepsPerHour) => (
        <option key={stepsPerHour} value={stepsPerHour}>{messages.sunStepsOption(stepsPerHour)}</option>
      ))}
    </select>
  );
}
