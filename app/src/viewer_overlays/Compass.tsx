// The compass of UX 8.1, top left of the 3D view: a ring with N that turns with the camera; a click shows the top view, north up.
import { messages } from "../messages";
import { northNeedleScreenAngle } from "../viewer/compass";
import type { ViewportTheme } from "../viewer/scene";
import "./overlays.css";

interface CompassProps {
  yawDegrees: number;
  northDegrees: number;
  theme: ViewportTheme;
  onViewTop: () => void;
}

const RING_RADIUS = 27;
const LETTER_RADIUS = 19;
const NEEDLE_RADIUS = 12;

export function Compass({ yawDegrees, northDegrees, theme, onViewTop }: CompassProps) {
  const needleDegrees = northNeedleScreenAngle(yawDegrees, northDegrees);
  const needleRadians = (needleDegrees * Math.PI) / 180;
  return (
    <button type="button" className="viewer-overlay viewer-compass" data-viewport-theme={theme} aria-label={messages.compass} title={messages.topView}
            onClick={onViewTop}>
      <svg viewBox="-32 -32 64 64" width="64" height="64" aria-hidden="true">
        <circle r={RING_RADIUS} fill="none" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1.5" />
        <g transform={`rotate(${needleDegrees})`}>
          <path d={`M0 ${-NEEDLE_RADIUS} L4 -2 L0 -4 L-4 -2 Z`} fill="currentColor" />
          <line x1="0" y1="2" x2="0" y2={NEEDLE_RADIUS} stroke="currentColor" strokeOpacity="0.4" strokeWidth="1.5" />
        </g>
        {/* the N stays upright while it moves round with the needle */}
        <text x={LETTER_RADIUS * Math.sin(needleRadians)} y={-LETTER_RADIUS * Math.cos(needleRadians)} textAnchor="middle" dominantBaseline="central"
              fill="currentColor" fontSize="12" fontWeight="700">{messages.northLetter}</text>
      </svg>
    </button>
  );
}
