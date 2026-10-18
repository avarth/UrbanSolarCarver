// The plane angle of the angle rule (UX 7): one angle for every test surface, or one per compass direction the test surfaces
// face, in the engine's order [N, NE, E, SE, S, SW, W, NW].
import { useId } from "react";
import { messages } from "../../messages";
import { NumberInput, type ControlProps } from "./NumberInput";

const DIRECTION_COUNT = 8;

interface TiltedPlaneAnglesProps extends ControlProps {
  value: number | number[] | null;
  /** The angle the directions start from when the user switches from one angle to one per direction without an angle set. */
  startingAngle: number | null;
  unit: string;
  onAngles: (value: number | number[] | null) => void;
}

export function TiltedPlaneAngles({ value, startingAngle, unit, onAngles, inputId, labelId, invalid, describedBy, disabled }: TiltedPlaneAnglesProps) {
  const choiceName = useId();
  const perDirection = Array.isArray(value);
  const firstAngle = Array.isArray(value) ? (value[0] ?? null) : value;
  const chooseOneAngle = () => onAngles(firstAngle);
  const choosePerDirection = () => onAngles(Array(DIRECTION_COUNT).fill(firstAngle ?? startingAngle ?? 0));
  return (
    <div role="group" aria-labelledby={labelId} className="setting-angles">
      <div className="setting-choice-row">
        <label><input type="radio" name={choiceName} value="one" checked={!perDirection} disabled={disabled} onChange={chooseOneAngle} />
          {messages.oneAngle}</label>
        <label><input type="radio" name={choiceName} value="per_direction" checked={perDirection} disabled={disabled} onChange={choosePerDirection} />
          {messages.oneAnglePerDirection}</label>
      </div>
      {perDirection ? (
        <div className="setting-angle-grid">
          {messages.compassDirections.map((direction, index) => (
            <label key={direction} className="setting-angle-direction">
              <span>{direction}</span>
              <NumberInput id={index === 0 ? inputId : undefined} className="setting-number setting-number-short"
                           ariaLabel={messages.angleTowards(direction)} value={value[index] ?? null} mayBeEmpty={false}
                           invalid={invalid} describedBy={describedBy} disabled={disabled}
                           onValue={(angle) => onAngles(value.map((previous, position) => (position === index ? angle! : previous)))} />
              <span className="setting-unit">{unit}</span>
            </label>
          ))}
        </div>
      ) : (
        <div className="setting-control">
          <NumberInput id={inputId} ariaLabelledBy={labelId} value={firstAngle} mayBeEmpty invalid={invalid} describedBy={describedBy} disabled={disabled} onValue={onAngles} />
          <span className="setting-unit">{unit}</span>
        </div>
      )}
    </div>
  );
}
