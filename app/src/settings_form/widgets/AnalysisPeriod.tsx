// The analysis period (R2 4.3): the six period settings as one control. A year strip of twelve months with a start and an end date
// handle, an hour strip of 0 to 23 h with a start and an end hour handle, a row of presets that set the dates and keep the hours,
// and the period in words, which opens fields to type the exact day, month and hour of each end.
//
// A start after the end is drawn wrapped: dates across the new year, hours across midnight. Every change goes through
// withOvernightHoursOnOneDateAsOneNight (analysis_period.ts), so hours across midnight on one date are one night. A period stored
// as one date with hours across midnight (a hand-edited config, an older save) is shown as the engine runs it: the whole year on the
// year strip, "Every day, 22 to 2 h" in words; it is not changed until the next change in the control.
//
// How changes are sent: a key or a preset is one change; a drag is held here and sent once, on release; the typed fields are sent
// when one is left or Enter is pressed, or when the fields close (and a month when it is chosen). So a value on the way (end hour
// "1" on the way to "18", a drag that crosses the end hour and comes back) never moves the end date. The form saves once the
// changes stop.
import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { messages } from "../../messages";
import {
  changedPeriodSettings, dateHandleValueAfterKey, dateRangeSegments, dayOfYearAt, daysInMonth, DAYS_IN_YEAR, handlePositionOf, handleValueOf,
  hourAt, hourHandleValueAfterKey, hourRangeSegments, HOURS_IN_DAY, monthDayOf, PERIOD_PRESETS, periodFromSettings, periodInWords,
  periodWithDayTyped, periodWithHandleAt, periodWithMonthChosen, presetMatches, presetPeriod, withOvernightHoursOnOneDateAsOneNight,
  type AnalysisPeriodField, type Period, type PeriodEnd, type PeriodHandle, type RangeSegment,
} from "../analysis_period";
import { ANALYSIS_PERIOD_FIELDS } from "../presentation";
import { NumberInput, type ControlProps } from "./NumberInput";

export type { AnalysisPeriodField } from "../analysis_period";

interface AnalysisPeriodProps extends ControlProps {
  values: Record<AnalysisPeriodField, number | null>;
  onChange: (values: Partial<Record<AnalysisPeriodField, number | null>>) => void;
}

// Where a handle is drawn while the period is not set yet (the words say so): the whole year, every hour.
const WHOLE_YEAR_EVERY_HOUR: Period = { startMonth: 1, startDay: 1, startHour: 0, endMonth: 12, endDay: 31, endHour: 23 };

// Handles closer than this on the strip lie on one spot: the direction of the drag picks the one it moves (left the start, right
// the end), as on the balance temperature slider. The width of a handle (settings_form.css, --period-handle-width).
const HANDLES_ON_ONE_SPOT_PIXELS = 10;

/** What a handle says to a screen reader: "21 December", "10 h". */
function spokenValueOf(period: Period, handle: PeriodHandle): string {
  if (handle === "start_hour" || handle === "end_hour") return messages.periodHourSpoken(handleValueOf(period, handle));
  const { month, day } = monthDayOf(handleValueOf(period, handle));
  return messages.periodDateSpoken(month, day);
}

export function AnalysisPeriod({ values, onChange, inputId, labelId, invalid, describedBy, disabled, onRefusedInput }: AnalysisPeriodProps) {
  const stored = periodFromSettings(values);
  const current = stored ?? WHOLE_YEAR_EVERY_HOUR;
  // The period of a drag, as dragged (the end date of one night is applied to what is shown and sent, not kept), else null.
  // Otherwise the stored period is shown as it is.
  const [draggedPeriod, setDraggedPeriod] = useState<Period | null>(null);
  const draggedPeriodNow = useRef<Period | null>(null);
  const shown = draggedPeriod === null ? current : withOvernightHoursOnOneDateAsOneNight(draggedPeriod);
  const [typing, setTyping] = useState(false);
  const typedFieldsId = useId();

  const send = (next: Period) => {
    const changes = changedPeriodSettings(values, withOvernightHoursOnOneDateAsOneNight(next));
    if (Object.keys(changes).length > 0) onChange(changes);
  };
  const drag = {
    moveTo: (handle: PeriodHandle, value: number) => {
      draggedPeriodNow.current = periodWithHandleAt(draggedPeriodNow.current ?? current, handle, value);
      setDraggedPeriod(draggedPeriodNow.current);
    },
    end: () => {
      const dragged = draggedPeriodNow.current;
      draggedPeriodNow.current = null;
      setDraggedPeriod(null);
      if (dragged !== null) send(dragged);
    },
  };
  const onKey = (handle: PeriodHandle, event: KeyboardEvent) => {
    const isDate = handle === "start_date" || handle === "end_date";
    const value = (isDate ? dateHandleValueAfterKey : hourHandleValueAfterKey)(handleValueOf(current, handle), event.key);
    if (value === null || disabled || draggedPeriodNow.current !== null) return;
    event.preventDefault();
    send(periodWithHandleAt(current, handle, value));
  };
  const strip = { period: shown, invalid, describedBy, disabled, drag, onKey };
  const words = stored === null ? messages.periodNotSet : periodInWords(shown);

  return (
    <div role="group" aria-labelledby={labelId} className="period-control">
      <PeriodStrip {...strip} handles={["start_date", "end_date"]} startHandleId={inputId} segments={dateRangeSegments(shown)} valueAt={dayOfYearAt}
                   valueRange={[1, DAYS_IN_YEAR]}
                   cells={messages.monthInitials.map((initial, index) => ({ label: initial, length: daysInMonth(index + 1) }))} />
      <PeriodStrip {...strip} handles={["start_hour", "end_hour"]} segments={hourRangeSegments(shown)} valueAt={hourAt} valueRange={[0, HOURS_IN_DAY - 1]}
                   cells={Array.from({ length: HOURS_IN_DAY }, (_, hour) => ({ label: hour % 6 === 0 ? String(hour) : "", length: 1 }))} />
      <div role="group" aria-label={messages.periodPresets} className="period-presets">
        {PERIOD_PRESETS.map((preset) => (
          <button key={preset} type="button" className="period-preset" disabled={disabled} aria-pressed={stored !== null && presetMatches(preset, current)}
                  onClick={() => send(presetPeriod(preset, current))}>
            {messages.periodPresetNames[preset]}
          </button>
        ))}
      </div>
      <button type="button" className="period-words" aria-label={messages.periodWordsButton(words)} aria-expanded={typing}
              aria-controls={typing ? typedFieldsId : undefined} disabled={disabled}
              onClick={() => {
                if (typing) onRefusedInput?.(null);       // a refusal of a closed field stands no more
                setTyping(!typing);
              }}>
        {words}
      </button>
      {typing && <TypedPeriod id={typedFieldsId} period={current} onPeriod={send} invalid={invalid} describedBy={describedBy} disabled={disabled}
                              onRefusedInput={onRefusedInput} />}
    </div>
  );
}

interface PeriodStripProps {
  period: Period;
  handles: [PeriodHandle, PeriodHandle];
  /** The id of the start handle: the input the field's label names, which a link to the setting focuses. */
  startHandleId?: string;
  segments: RangeSegment[];
  cells: { label: string; length: number }[];
  valueAt: (fraction: number) => number;
  valueRange: [number, number];
  invalid: boolean;
  describedBy: string | undefined;
  disabled: boolean;
  drag: { moveTo: (handle: PeriodHandle, value: number) => void; end: () => void };
  onKey: (handle: PeriodHandle, event: KeyboardEvent) => void;
}

/** A drag on a strip: its pointer, the handle it moves (null until the first move where the handles lie on one spot), where it began. */
interface StripDrag {
  pointerId: number;
  handle: PeriodHandle | null;
  pressedValue: number;
}

function PeriodStrip({ period, handles, startHandleId, segments, cells, valueAt, valueRange, invalid, describedBy, disabled, drag, onKey }: PeriodStripProps) {
  const [startHandle, endHandle] = handles;
  const stripElement = useRef<HTMLDivElement>(null);
  const handleElements = useRef<Partial<Record<PeriodHandle, HTMLDivElement | null>>>({});
  const stripDrag = useRef<StripDrag | null>(null);
  const fractionAt = (clientX: number) => {
    const bounds = stripElement.current!.getBoundingClientRect();
    return bounds.width > 0 ? (clientX - bounds.left) / bounds.width : 0;
  };
  const move = (handle: PeriodHandle, value: number) => {
    handleElements.current[handle]?.focus();
    drag.moveTo(handle, value);
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();         // no text selection; the handle the drag moves takes the focus
    const width = stripElement.current!.getBoundingClientRect().width;
    const pressed = fractionAt(event.clientX);
    const startDistance = Math.abs(pressed - handlePositionOf(period, startHandle)) * width;
    const endDistance = Math.abs(pressed - handlePositionOf(period, endHandle)) * width;
    // Pressed on two handles that lie on one spot: the first move picks one. Pressed elsewhere: the nearer handle jumps there.
    const onOneSpot = Math.abs(handlePositionOf(period, startHandle) - handlePositionOf(period, endHandle)) * width < HANDLES_ON_ONE_SPOT_PIXELS;
    const pressedOnTheSpot = onOneSpot && Math.min(startDistance, endDistance) < HANDLES_ON_ONE_SPOT_PIXELS;
    const handle = pressedOnTheSpot ? null : startDistance <= endDistance ? startHandle : endHandle;
    stripDrag.current = { pointerId: event.pointerId, handle, pressedValue: valueAt(pressed) };
    stripElement.current!.setPointerCapture?.(event.pointerId);
    if (handle === null) handleElements.current[startHandle]?.focus();
    else move(handle, valueAt(pressed));
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const dragNow = stripDrag.current;
    if (dragNow === null || dragNow.pointerId !== event.pointerId) return;
    const value = valueAt(fractionAt(event.clientX));
    if (dragNow.handle === null) {
      if (value === dragNow.pressedValue) return;
      dragNow.handle = value < dragNow.pressedValue ? startHandle : endHandle;
    }
    move(dragNow.handle, value);
  };
  // The release, a cancel, or the capture lost (the release outside the window): the drag is sent once.
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (stripDrag.current === null || stripDrag.current.pointerId !== event.pointerId) return;
    stripDrag.current = null;
    drag.end();
  };

  return (
    <div ref={stripElement} className="period-strip" data-invalid={invalid ? "true" : undefined} data-disabled={disabled ? "true" : undefined}
         onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag}>
      {segments.map((segment) => (
        <span key={segment.start} className="period-range" aria-hidden="true"
              style={{ "--range-start": segment.start, "--range-end": segment.end } as CSSProperties} />
      ))}
      <span className="period-strip-cells" aria-hidden="true">
        {cells.map((cell, index) => (
          <span key={index} className="period-strip-cell" style={{ flexGrow: cell.length }}>{cell.label}</span>
        ))}
      </span>
      {handles.map((handle) => (
        <div key={handle} ref={(element) => { handleElements.current[handle] = element; }} id={handle === startHandle ? startHandleId : undefined}
             role="slider" tabIndex={disabled ? -1 : 0} className="period-handle" style={{ "--handle-position": handlePositionOf(period, handle) } as CSSProperties}
             aria-label={messages.periodHandleNames[handle]} aria-orientation="horizontal" aria-valuemin={valueRange[0]} aria-valuemax={valueRange[1]}
             aria-valuenow={handleValueOf(period, handle)} aria-valuetext={spokenValueOf(period, handle)} aria-invalid={invalid}
             aria-describedby={describedBy} aria-disabled={disabled ? true : undefined} onKeyDown={(event) => onKey(handle, event)} />
      ))}
    </div>
  );
}

interface TypedPeriodProps {
  id: string;
  period: Period;
  onPeriod: (period: Period) => void;
  invalid: boolean;
  describedBy: string | undefined;
  disabled: boolean;
  onRefusedInput?: (message: string | null) => void;
}

const TYPED_ENDS = [
  { end: "start", title: messages.periodFrom, day: "start_day", month: "start_month", hour: "start_hour", periodHour: "startHour" },
  { end: "end", title: messages.periodTo, day: "end_day", month: "end_month", hour: "end_hour", periodHour: "endHour" },
] as const;

/**
 * The exact values of the period: for each end, the day (held to the month's length), the month and the hour. A typed number is
 * held here and sent when its field is left, Enter is pressed or the fields close without either (the words clicked, the step
 * closed); a month is sent when it is chosen, its day held to its length.
 * Each number field keeps its own refusal; the field shows the first one standing, so a valid hour never hides a refused day.
 */
function TypedPeriod({ id, period, onPeriod, invalid, describedBy, disabled, onRefusedInput }: TypedPeriodProps) {
  const [typedPeriod, setTypedPeriod] = useState<Period | null>(null);
  // The typed period and the latest way to send it, for the fields closing: their unmount sends what is typed and not yet sent.
  const typedPeriodNow = useRef<Period | null>(null);
  const sendPeriod = useRef(onPeriod);
  sendPeriod.current = onPeriod;
  const holdTyped = (typed: Period | null) => {
    typedPeriodNow.current = typed;
    setTypedPeriod(typed);
  };
  const sendTyped = () => {
    const typed = typedPeriodNow.current;
    if (typed === null) return;
    holdTyped(null);
    sendPeriod.current(typed);
  };
  useEffect(() => () => {
    const typed = typedPeriodNow.current;
    typedPeriodNow.current = null;
    if (typed !== null) sendPeriod.current(typed);
  }, []);
  const shown = typedPeriod ?? period;
  const refusals = useRef<Partial<Record<AnalysisPeriodField, string | null>>>({});
  const refusedIn = (field: AnalysisPeriodField) => (refusal: string | null) => {
    refusals.current = { ...refusals.current, [field]: refusal };
    onRefusedInput?.(ANALYSIS_PERIOD_FIELDS.map((name) => refusals.current[name] ?? null).find((standing) => standing !== null) ?? null);
  };
  const month = (end: PeriodEnd) => (end === "start" ? shown.startMonth : shown.endMonth);
  return (
    <div id={id} className="setting-period" onBlur={sendTyped} onKeyDown={(event) => { if (event.key === "Enter") sendTyped(); }}>
      {TYPED_ENDS.map((typedEnd) => (
        <div key={typedEnd.end} className="setting-period-row">
          <span className="setting-period-end">{typedEnd.title}</span>
          <NumberInput className="setting-number setting-number-short" ariaLabel={messages.periodFieldNames[typedEnd.day]}
                       value={typedEnd.end === "start" ? shown.startDay : shown.endDay} mayBeEmpty={false} minimum={1} maximum={daysInMonth(month(typedEnd.end))}
                       wholeNumbers invalid={invalid} describedBy={describedBy} disabled={disabled}
                       onValue={(day) => holdTyped(periodWithDayTyped(shown, typedEnd.end, day!))} onRefused={refusedIn(typedEnd.day)} />
          <select className="setting-select" aria-label={messages.periodFieldNames[typedEnd.month]} value={month(typedEnd.end)} aria-invalid={invalid}
                  aria-describedby={describedBy} disabled={disabled}
                  onChange={(event) => {
                    holdTyped(null);
                    onPeriod(periodWithMonthChosen(shown, typedEnd.end, Number(event.target.value)));
                  }}>
            {messages.monthNames.map((monthName, index) => <option key={monthName} value={index + 1}>{monthName}</option>)}
          </select>
          <NumberInput className="setting-number setting-number-short" ariaLabel={messages.periodTypedHourNames[typedEnd.hour]} value={shown[typedEnd.periodHour]}
                       mayBeEmpty={false} minimum={0} maximum={HOURS_IN_DAY - 1} wholeNumbers invalid={invalid} describedBy={describedBy} disabled={disabled}
                       onValue={(hour) => holdTyped({ ...shown, [typedEnd.periodHour]: hour! })} onRefused={refusedIn(typedEnd.hour)} />
          <span className="setting-unit">{messages.hourUnit}</span>
        </div>
      ))}
    </div>
  );
}
