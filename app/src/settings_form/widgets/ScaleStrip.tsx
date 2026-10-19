// A strip with a scale and two handles (role slider), the drawing the analysis period (its year strip and hour strip) and the
// balance temperature share. It draws the scale (cells with their labels), the range between the handles, the two handles, and
// over each handle a bubble with its exact value, always shown. The two bubbles move apart where they would overlap and stay over
// the strip (valueBubbleShifts).
//
// A press on the strip moves the nearer handle there. Where the two handles lie on one spot, the first move of the drag picks the
// handle by its direction: to the left the start, to the right the end. The caller holds the values: it is told each move of a
// drag and its end, and each key, and says which handle a key moved; that handle takes the focus. Keys and drags are ignored
// while the strip is disabled, and keys while a drag is under way.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import type { RangeSegment } from "../analysis_period";

/** One handle of a strip, as the caller describes it. */
export interface ScaleStripHandle<HandleName extends string> {
  name: HandleName;
  /** Where the handle is drawn, as a fraction of the strip. */
  position: number;
  accessibleName: string;
  /** Its value for aria-valuenow, on the strip's range. */
  valueNow: number;
  /** What it says to a screen reader: "21 December", "35 °C" (the value itself, also off the strip). */
  spokenValue: string;
  /** What its bubble shows: "21 Dec", "14.5 °C". */
  bubbleText: string;
  /** The id of the handle, where the field's label names it (a link to the setting focuses it). */
  id?: string;
}

/** A cell of the scale: its label (empty for an unlabelled tick) and its length, relative to the other cells. */
export interface ScaleStripCell {
  label: string;
  length: number;
}

interface ScaleStripProps<HandleName extends string> {
  /** The start handle, then the end handle: their order on the page and for Tab. */
  handles: [ScaleStripHandle<HandleName>, ScaleStripHandle<HandleName>];
  segments: RangeSegment[];
  cells: ScaleStripCell[];
  /** The value under the pointer, *fraction* of the way along the strip. */
  valueAt: (fraction: number) => number;
  valueRange: [number, number];
  invalid: boolean;
  describedBy: string | undefined;
  disabled: boolean;
  onDragMove: (handle: HandleName, value: number) => void;
  onDragEnd: () => void;
  /** A key on *handle*: returns the handle the key moved, or null for a key that moves nothing. */
  onKey: (handle: HandleName, key: string) => HandleName | null;
}

// Handles closer than this on the strip lie on one spot: the direction of the drag picks the one it moves. The width of a period
// handle (settings_form.css, --scale-strip-handle-width).
const HANDLES_ON_ONE_SPOT_PIXELS = 10;
// The least space between the two bubbles.
const GAP_BETWEEN_BUBBLES_PIXELS = 4;

interface BubbleLayout {
  /** The centres of the two handles, start then end, in pixels from the strip's left edge. */
  centres: [number, number];
  widths: [number, number];
  stripWidth: number;
  gap: number;
}

/**
 * How far each bubble moves sideways from centred over its handle, in pixels, start then end: bubbles that would overlap move apart
 * by the same amount (on one spot the start's to the left), then both are kept over the strip, the other pushed along to keep the
 * gap. A strip not measured yet (width 0) leaves both centred.
 */
export function valueBubbleShifts({ centres, widths, stripWidth, gap }: BubbleLayout): [number, number] {
  if (stripWidth <= 0) return [0, 0];
  const startIsLeft = centres[0] <= centres[1];
  const [left, right] = startIsLeft ? [0, 1] : [1, 0];
  const centredLefts = [centres[0] - widths[0] / 2, centres[1] - widths[1] / 2];
  let leftBubbleLeft = centredLefts[left], rightBubbleLeft = centredLefts[right];
  const overlap = leftBubbleLeft + widths[left] + gap - rightBubbleLeft;
  if (overlap > 0) {
    leftBubbleLeft -= overlap / 2;
    rightBubbleLeft += overlap / 2;
  }
  const keptOver = (bubbleLeft: number, width: number) => Math.min(Math.max(bubbleLeft, 0), stripWidth - width);
  leftBubbleLeft = keptOver(leftBubbleLeft, widths[left]);
  rightBubbleLeft = keptOver(Math.max(rightBubbleLeft, leftBubbleLeft + widths[left] + gap), widths[right]);
  leftBubbleLeft = Math.min(leftBubbleLeft, rightBubbleLeft - gap - widths[left]);
  const shifts: [number, number] = [0, 0];
  shifts[left] = leftBubbleLeft - centredLefts[left];
  shifts[right] = rightBubbleLeft - centredLefts[right];
  return shifts;
}

/** A drag on a strip: its pointer, the handle it moves (null until the first move where the handles lie on one spot), where it began. */
interface StripDrag<HandleName extends string> {
  pointerId: number;
  handle: HandleName | null;
  pressedValue: number;
}

export function ScaleStrip<HandleName extends string>({ handles, segments, cells, valueAt, valueRange, invalid, describedBy, disabled, onDragMove,
                                                        onDragEnd, onKey }: ScaleStripProps<HandleName>) {
  const [startHandle, endHandle] = handles;
  const stripElement = useRef<HTMLDivElement>(null);
  const handleElements = useRef<Partial<Record<HandleName, HTMLDivElement | null>>>({});
  const bubbleElements = useRef<(HTMLSpanElement | null)[]>([]);
  const stripDrag = useRef<StripDrag<HandleName> | null>(null);

  // The widths the bubbles are placed by, measured after each change of their text and each resize of the strip.
  const [measured, setMeasured] = useState({ stripWidth: 0, bubbleWidths: [0, 0] as [number, number] });
  const measureBubbles = () => {
    const stripWidth = stripElement.current?.clientWidth ?? 0;
    const bubbleWidths: [number, number] = [bubbleElements.current[0]?.offsetWidth ?? 0, bubbleElements.current[1]?.offsetWidth ?? 0];
    setMeasured((before) => (before.stripWidth === stripWidth && before.bubbleWidths.every((width, index) => width === bubbleWidths[index])
      ? before : { stripWidth, bubbleWidths }));
  };
  useLayoutEffect(measureBubbles, [startHandle.bubbleText, endHandle.bubbleText]);
  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || stripElement.current === null) return;
    const observer = new ResizeObserver(measureBubbles);
    observer.observe(stripElement.current);
    return () => observer.disconnect();
  }, []);
  const bubbleShifts = valueBubbleShifts({
    centres: [startHandle.position * measured.stripWidth, endHandle.position * measured.stripWidth],
    widths: measured.bubbleWidths, stripWidth: measured.stripWidth, gap: GAP_BETWEEN_BUBBLES_PIXELS,
  });

  const fractionAt = (clientX: number) => {
    const bounds = stripElement.current!.getBoundingClientRect();
    return bounds.width > 0 ? (clientX - bounds.left) / bounds.width : 0;
  };
  const move = (handle: HandleName, value: number) => {
    handleElements.current[handle]?.focus();
    onDragMove(handle, value);
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();         // no text selection; the handle the drag moves takes the focus
    const width = stripElement.current!.getBoundingClientRect().width;
    const pressed = fractionAt(event.clientX);
    const startDistance = Math.abs(pressed - startHandle.position) * width;
    const endDistance = Math.abs(pressed - endHandle.position) * width;
    // Pressed on two handles that lie on one spot: the first move picks one. Pressed elsewhere: the nearer handle jumps there.
    const onOneSpot = Math.abs(startHandle.position - endHandle.position) * width < HANDLES_ON_ONE_SPOT_PIXELS;
    const pressedOnTheSpot = onOneSpot && Math.min(startDistance, endDistance) < HANDLES_ON_ONE_SPOT_PIXELS;
    const handle = pressedOnTheSpot ? null : startDistance <= endDistance ? startHandle.name : endHandle.name;
    stripDrag.current = { pointerId: event.pointerId, handle, pressedValue: valueAt(pressed) };
    stripElement.current!.setPointerCapture?.(event.pointerId);
    if (handle === null) handleElements.current[startHandle.name]?.focus();
    else move(handle, valueAt(pressed));
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const dragNow = stripDrag.current;
    if (dragNow === null || dragNow.pointerId !== event.pointerId) return;
    const value = valueAt(fractionAt(event.clientX));
    if (dragNow.handle === null) {
      if (value === dragNow.pressedValue) return;
      dragNow.handle = value < dragNow.pressedValue ? startHandle.name : endHandle.name;
    }
    move(dragNow.handle, value);
  };
  // The release, a cancel, or the capture lost (the release outside the window): the drag ends once.
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (stripDrag.current === null || stripDrag.current.pointerId !== event.pointerId) return;
    stripDrag.current = null;
    onDragEnd();
  };
  const onHandleKeyDown = (handle: HandleName, event: KeyboardEvent) => {
    if (disabled || stripDrag.current !== null) return;
    const moved = onKey(handle, event.key);
    if (moved === null) return;
    event.preventDefault();
    if (moved !== handle) handleElements.current[moved]?.focus();
  };

  return (
    <div ref={stripElement} className="scale-strip" data-invalid={invalid ? "true" : undefined} data-disabled={disabled ? "true" : undefined}
         onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag}>
      {segments.map((segment) => (
        <span key={segment.start} className="scale-strip-range" aria-hidden="true"
              style={{ "--range-start": segment.start, "--range-end": segment.end } as CSSProperties} />
      ))}
      <span className="scale-strip-cells" aria-hidden="true">
        {cells.map((cell, index) => (
          <span key={index} className="scale-strip-cell" style={{ flexGrow: cell.length }}>{cell.label}</span>
        ))}
      </span>
      {handles.map((handle, index) => {
        const positionStyle = { "--handle-position": handle.position } as CSSProperties;
        return [
          <div key={handle.name} ref={(element) => { handleElements.current[handle.name] = element; }} id={handle.id} role="slider"
               tabIndex={disabled ? -1 : 0} className="scale-strip-handle" style={positionStyle} aria-label={handle.accessibleName} aria-orientation="horizontal" aria-valuemin={valueRange[0]} aria-valuemax={valueRange[1]}
               aria-valuenow={handle.valueNow} aria-valuetext={handle.spokenValue} aria-invalid={invalid} aria-describedby={describedBy}
               aria-disabled={disabled ? true : undefined} onKeyDown={(event) => onHandleKeyDown(handle.name, event)} />,
          // Seen, not read: the handle says its value itself.
          <span key={`${handle.name}-bubble`} ref={(element) => { bubbleElements.current[index] = element; }} className="scale-strip-bubble"
                aria-hidden="true"
                style={{ ...positionStyle, "--bubble-shift": `${bubbleShifts[index]}px` } as CSSProperties}>
            {handle.bubbleText}
          </span>,
        ];
      })}
    </div>
  );
}
