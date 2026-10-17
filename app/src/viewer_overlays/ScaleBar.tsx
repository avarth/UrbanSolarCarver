// The scale bar of UX 8.1, bottom centre of the 3D view: a round length, 100 to 250 px long at the current zoom.
import { scaleBarLabel, scaleBarLength } from "../viewer/scale_bar";
import type { ViewportTheme } from "../viewer/scene";
import "./overlays.css";

interface ScaleBarProps {
  metresPerPixel: number;
  theme: ViewportTheme;
}

export function ScaleBar({ metresPerPixel, theme }: ScaleBarProps) {
  if (!(metresPerPixel > 0) || !Number.isFinite(metresPerPixel)) return null;
  const { metres, pixels } = scaleBarLength(metresPerPixel);
  return (
    <div className="viewer-overlay viewer-scale-bar" data-viewport-theme={theme}>
      <span>{scaleBarLabel(metres)}</span>
      <div className="viewer-scale-bar-line" style={{ width: `${pixels}px` }} aria-hidden="true" />
    </div>
  );
}
