// The legend along the bottom of Simulate's view (simulate design, section 3): the colour scale of the selected study, with the two
// ends of its colour range as draggable marks (user, 2026-10-28: a low and a high threshold; values beyond an end take that end's
// colour, so the palette spreads over the range that matters), a switch between the value in the study's unit (first) and the share
// of the no-build value (0 to 100 %), each with its palette. By value the low end is the study's target and the high end its target_max, both saved
// with the study; by share they are percentages. A press or drag on the bar moves the nearer end, which is given once, at the
// release; on a mark (a slider) the arrow keys move it by 1 % of the bar, Page Up and Page Down by 10 %, Home and End to the ends of
// the bar, and Delete (or Backspace) puts it back to its default.
import { useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { messages } from "../messages";
import type { ColourBy } from "../viewer/study_values";
import { formattedNumber, withUnit } from "../format_numbers";
import { studyPaletteColour, type StudyPalette } from "../viewer/study_palettes";
import "./overlays.css";

type End = "low" | "high";

export interface TargetLegendProps {
  /** The metric's label, which the scale's title gives with the unit. */
  label: string;
  unit: string;
  mode: ColourBy;
  /** The extent of the bar: 0 to 100 (%) by share, 0 to the highest value otherwise. */
  scale: [number, number];
  /** The two ends of the colour range on the bar. */
  low: number;
  high: number;
  palette: StudyPalette;
  /** An end the user set, or null to put it back to its default: at the end of a drag, or at each key. */
  onRangeEndChange: (end: End, value: number | null) => void;
  /** Switches between share and value. */
  onColourByChange?: (colourBy: ColourBy) => void;
  /** The ends cannot be moved now (a run of the project). */
  disabled?: boolean;
}

const RAMP_STOPS = 21;
const KEY_STEP_SHARE = 0.01;
const PAGE_STEP_SHARE = 0.1;
const SIGNIFICANT_DIGITS = 6;

/** *value* within [low, high], without the float noise of a sum of steps (0.1 + 0.2). */
function kept(value: number, low: number, high: number): number {
  return Number(Math.min(high, Math.max(low, value)).toPrecision(SIGNIFICANT_DIGITS));
}

export function TargetLegend({ label, unit, mode, scale, low, high, palette, onRangeEndChange, onColourByChange,
                              disabled = false }: TargetLegendProps) {
  const bar = useRef<HTMLDivElement>(null);
  const marks = { low: useRef<HTMLDivElement>(null), high: useRef<HTMLDivElement>(null) };
  // While a drag goes on, its end follows the pointer; the value is given at the release. The ref has the latest move, which a
  // release that comes before the next render still finds.
  const [dragged, setDraggedState] = useState<{ pointerId: number; end: End; value: number } | null>(null);
  const drag = useRef(dragged);
  const setDragged = (next: typeof dragged) => {
    drag.current = next;
    setDraggedState(next);
  };
  const [scaleLow, scaleHigh] = scale;
  const span = scaleHigh > scaleLow ? scaleHigh - scaleLow : 1;
  const shownLow = dragged?.end === "low" ? dragged.value : low;
  const shownHigh = dragged?.end === "high" ? dragged.value : high;
  const shareOf = (value: number) => Math.min(1, Math.max(0, (value - scaleLow) / span));
  const byShare = mode === "share";
  const format = (value: number) => (byShare ? withUnit(formattedNumber(value), "%") : formattedNumber(value));
  // An end stays a key step (1 % of the bar) short of the other, so the range never shrinks to one value (two marks on one spot
  // hide the high end, and the palette would span one unit).
  const gap = KEY_STEP_SHARE * span;
  const limitsOf = (end: End): [number, number] => (end === "low"
    ? [scaleLow, kept(shownHigh - gap, scaleLow, scaleHigh)] : [kept(shownLow + gap, scaleLow, scaleHigh), scaleHigh]);

  const valueAt = (clientX: number, end: End) => {
    const bounds = bar.current!.getBoundingClientRect();
    const [from, to] = limitsOf(end);
    return kept(scaleLow + (bounds.width > 0 ? (clientX - bounds.left) / bounds.width : 0) * span, from, to);
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();          // no text selection; the mark takes the focus
    const bounds = bar.current!.getBoundingClientRect();
    const at = scaleLow + (bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0) * span;
    const end: End = Math.abs(at - shownLow) <= Math.abs(at - shownHigh) && !(at > shownHigh) ? "low" : "high";
    bar.current!.setPointerCapture?.(event.pointerId);
    marks[end].current?.focus();
    setDragged({ pointerId: event.pointerId, end, value: valueAt(event.clientX, end) });
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (current === null || current.pointerId !== event.pointerId) return;
    setDragged({ ...current, value: valueAt(event.clientX, current.end) });
  };
  // The release, a cancel, or the capture lost (the release outside the window): the drag ends once, where the mark was.
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    const ended = drag.current;
    if (ended === null || ended.pointerId !== event.pointerId) return;
    setDragged(null);
    onRangeEndChange(ended.end, ended.value);
  };
  const onKeyDown = (end: End) => (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || drag.current !== null) return;
    const from = end === "low" ? low : high;
    const [lowest, highest] = limitsOf(end);
    const moves: Record<string, () => number | null> = {
      ArrowRight: () => from + KEY_STEP_SHARE * span, ArrowUp: () => from + KEY_STEP_SHARE * span,
      ArrowLeft: () => from - KEY_STEP_SHARE * span, ArrowDown: () => from - KEY_STEP_SHARE * span,
      PageUp: () => from + PAGE_STEP_SHARE * span, PageDown: () => from - PAGE_STEP_SHARE * span,
      Home: () => lowest, End: () => highest, Delete: () => null, Backspace: () => null,
    };
    const move = moves[event.key];
    if (move === undefined) return;
    event.preventDefault();
    const next = move();
    onRangeEndChange(end, next === null ? null : kept(next, lowest, highest));
  };

  // The bar as the view colours it: the palette between the two ends, each end's colour beyond it.
  const rangeSpan = shownHigh > shownLow ? shownHigh - shownLow : 1;
  const colourAt = (share: number) => studyPaletteColour(palette, (scaleLow + share * span - shownLow) / rangeSpan);
  const gradient = `linear-gradient(to right, ${Array.from({ length: RAMP_STOPS }, (_, stop) => colourAt(stop / (RAMP_STOPS - 1))).join(", ")})`;
  const title = byShare ? messages.shareLegend(label) : messages.metricOption(label, unit);
  const mark = (end: End) => {
    const value = end === "low" ? shownLow : shownHigh;
    return (
      <div ref={marks[end]} role="slider" tabIndex={disabled ? -1 : 0} className="target-legend-mark" data-end={end}
           style={{ left: `${shareOf(value) * 100}%` } as CSSProperties} title={messages.rangeEndHint}
           aria-label={end === "low" ? messages.rangeLow : messages.rangeHigh} aria-orientation="horizontal"
           aria-valuemin={limitsOf(end)[0]} aria-valuemax={limitsOf(end)[1]} aria-valuenow={value}
           aria-valuetext={byShare ? withUnit(formattedNumber(value), "%") : withUnit(formattedNumber(value), unit)}
           aria-disabled={disabled ? true : undefined} onKeyDown={onKeyDown(end)} />
    );
  };
  return (
    <div className="viewer-overlay target-legend" role="group" aria-label={title}>
      <div className="target-legend-header">
        <div className="target-legend-title">{title}</div>
      </div>
      {onColourByChange !== undefined && (
        <div className="segmented-switch target-legend-colour-by" role="group" aria-label={messages.colourBy}>
          <button type="button" aria-pressed={mode === "value"} onClick={() => onColourByChange("value")}>{messages.colourByValue(unit)}</button>
          <button type="button" aria-pressed={byShare} onClick={() => onColourByChange("share")}>{messages.colourByShare}</button>
        </div>
      )}
      <div ref={bar} className="target-legend-bar" data-disabled={disabled ? "true" : undefined} style={{ background: gradient }}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}
           onLostPointerCapture={endDrag}>
        {mark("low")}
        {mark("high")}
      </div>
      <div className="target-legend-ends">
        <span>{format(scaleLow)}</span>
        <span>{format(scaleHigh)}</span>
      </div>
    </div>
  );
}
