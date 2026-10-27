// The legend along the bottom of Simulate's view (simulate design, section 3): the scale of the selected study's values in its unit,
// with the target as a draggable mark. By value, the scale is cividis from 0 to the highest value of the geometry shown, the part
// below the target in the muted colour the view gives those points. A press or drag on the scale moves the mark, and the target is
// given once, at the release; on the mark (a slider) the arrow keys move it by 1 % of the range, Page Up and Page Down by 10 %,
// Home and End to the ends, and Delete (or Backspace) clears it. By change from the maximum volume the scale is the change ramp, without a target,
// with the loss colour when some point lost.
import { useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { messages } from "../messages";
import { formattedNumber, withUnit } from "../steps/format_numbers";
import { changeRamp, cividis, colourToken, type ViewportTheme } from "../viewer/colour_scales";
import "./overlays.css";

export interface TargetLegendProps {
  /** The metric's label, which the scale's title gives with the unit. */
  label: string;
  unit: string;
  /** The scale, from 0 to the highest value (or change) of the geometry shown. */
  range: [number, number];
  target: number | null;
  /** The target the user set, or null when cleared: at the end of a drag, or at each key. */
  onTargetChange: (target: number | null) => void;
  mode: "value" | "change";
  /** By change: some point lost, so the loss colour is named. */
  hasLoss?: boolean;
  /** The target cannot be changed now (a run of the project). */
  disabled?: boolean;
  /** The viewport theme: the part below the target takes the colour the view gives those points on it. */
  theme?: ViewportTheme;
}

const RAMP_STOPS = 11;
const KEY_STEP_SHARE = 0.01;
const PAGE_STEP_SHARE = 0.1;
const SIGNIFICANT_DIGITS = 6;

function gradientOf(colourAt: (t: number) => string): string {
  return `linear-gradient(to right, ${Array.from({ length: RAMP_STOPS }, (_, stop) => colourAt(stop / (RAMP_STOPS - 1))).join(", ")})`;
}

/** *value* within the range, without the float noise of a sum of steps (0.1 + 0.2). */
function keptInRange(value: number, [low, high]: [number, number]): number {
  return Number(Math.min(high, Math.max(low, value)).toPrecision(SIGNIFICANT_DIGITS));
}

export function TargetLegend({ label, unit, range, target, onTargetChange, mode, hasLoss = false, disabled = false, theme = "light" }: TargetLegendProps) {
  const bar = useRef<HTMLDivElement>(null);
  const mark = useRef<HTMLDivElement>(null);
  // While a drag goes on, the mark follows the pointer; the target is given at the release. The ref has the latest move, which a
  // release that comes before the next render still finds.
  const [dragged, setDraggedState] = useState<{ pointerId: number; value: number } | null>(null);
  const drag = useRef(dragged);
  const setDragged = (next: { pointerId: number; value: number } | null) => {
    drag.current = next;
    setDraggedState(next);
  };
  const [low, high] = range;
  const span = high > low ? high - low : 1;
  const shown = dragged?.value ?? target;
  const shareOf = (value: number) => Math.min(1, Math.max(0, (value - low) / span));

  const valueAt = (clientX: number) => {
    const bounds = bar.current!.getBoundingClientRect();
    return keptInRange(low + (bounds.width > 0 ? (clientX - bounds.left) / bounds.width : 0) * span, range);
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();          // no text selection; the mark takes the focus
    bar.current!.setPointerCapture?.(event.pointerId);
    mark.current?.focus();
    setDragged({ pointerId: event.pointerId, value: valueAt(event.clientX) });
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current === null || drag.current.pointerId !== event.pointerId) return;
    setDragged({ pointerId: event.pointerId, value: valueAt(event.clientX) });
  };
  // The release, a cancel, or the capture lost (the release outside the window): the drag ends once, where the mark was.
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    const ended = drag.current;
    if (ended === null || ended.pointerId !== event.pointerId) return;
    setDragged(null);
    onTargetChange(ended.value);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || drag.current !== null) return;
    const from = target ?? low;
    const moves: Record<string, () => number | null> = {
      ArrowRight: () => from + KEY_STEP_SHARE * span, ArrowUp: () => from + KEY_STEP_SHARE * span,
      ArrowLeft: () => from - KEY_STEP_SHARE * span, ArrowDown: () => from - KEY_STEP_SHARE * span,
      PageUp: () => from + PAGE_STEP_SHARE * span, PageDown: () => from - PAGE_STEP_SHARE * span,
      Home: () => low, End: () => high, Delete: () => null, Backspace: () => null,
    };
    const move = moves[event.key];
    if (move === undefined) return;
    event.preventDefault();
    const next = move();
    onTargetChange(next === null ? null : keptInRange(next, range));
  };

  const valueMode = mode === "value";
  const title = valueMode ? messages.metricOption(label, unit) : messages.changeLegend(unit);
  return (
    <div className="viewer-overlay target-legend" role="group" aria-label={title}>
      <div className="target-legend-title">{title}</div>
      <div ref={bar} className="target-legend-bar" data-disabled={disabled ? "true" : undefined}
           style={{ background: gradientOf(valueMode ? cividis : changeRamp) }}
           onPointerDown={valueMode ? onPointerDown : undefined} onPointerMove={valueMode ? onPointerMove : undefined}
           onPointerUp={valueMode ? endDrag : undefined} onPointerCancel={valueMode ? endDrag : undefined}
           onLostPointerCapture={valueMode ? endDrag : undefined}>
        {valueMode && shown !== null && (
          <span className="target-legend-below" aria-hidden="true"
                style={{ width: `${shareOf(shown) * 100}%`, background: colourToken(theme === "dark" ? "below-target-on-dark" : "below-target") }} />
        )}
        {valueMode && (
          <div ref={mark} role="slider" tabIndex={disabled ? -1 : 0} className="target-legend-mark" data-empty={shown === null ? "true" : undefined}
               style={{ left: `${shareOf(shown ?? low) * 100}%` } as CSSProperties} title={messages.targetHint}
               aria-label={messages.target} aria-orientation="horizontal" aria-valuemin={low} aria-valuemax={high}
               aria-valuenow={shown ?? undefined} aria-valuetext={shown === null ? messages.noTarget : withUnit(formattedNumber(shown), unit)}
               aria-disabled={disabled ? true : undefined} onKeyDown={onKeyDown} />
        )}
      </div>
      <div className="target-legend-ends">
        <span>{formattedNumber(low)}</span>
        {!valueMode && hasLoss && (
          <span className="target-legend-loss"><span className="target-legend-loss-swatch" style={{ background: changeRamp(-1) }} aria-hidden="true" />{messages.changeLoss}</span>
        )}
        <span>{formattedNumber(high)}</span>
      </div>
    </div>
  );
}
