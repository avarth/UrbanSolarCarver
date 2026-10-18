// The axis gizmo of UX 8.1, bottom left of the 3D view: X, Y and Z as the camera sees them, in the axis colours and lettered.
// It has no background (R2 2): the axes are drawn straight on the viewport, the letters in the overlay ink of the viewport theme.
import { messages } from "../messages";
import { axisScreenDirections } from "../viewer/compass";
import type { ViewportTheme } from "../viewer/scene";
import "./overlays.css";

interface AxisGizmoProps {
  yawDegrees: number;
  elevationDegrees: number;
  theme: ViewportTheme;
}

const AXIS_LENGTH = 22;
const LETTER_DISTANCE = 29;
const AXES = [["x", "X", "--colour-axis-x"], ["y", "Y", "--colour-axis-y"], ["z", "Z", "--colour-axis-z"]] as const;

export function AxisGizmo({ yawDegrees, elevationDegrees, theme }: AxisGizmoProps) {
  const directions = axisScreenDirections(yawDegrees, elevationDegrees);
  return (
    <div className="viewer-overlay viewer-axis-gizmo" data-viewport-theme={theme} role="img" aria-label={messages.axisGizmo}>
      <svg viewBox="-36 -36 72 72" width="72" height="70" aria-hidden="true">
        {AXES.map(([axis, letter, colour]) => {
          const [right, up] = directions[axis];
          return (
            <g key={axis}>
              <line x1="0" y1="0" x2={right * AXIS_LENGTH} y2={-up * AXIS_LENGTH} stroke={`var(${colour})`} strokeWidth="2.5" strokeLinecap="round" />
              <text x={right * LETTER_DISTANCE} y={-up * LETTER_DISTANCE} textAnchor="middle" dominantBaseline="central" fill="currentColor">{letter}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
