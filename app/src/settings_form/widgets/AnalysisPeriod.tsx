// The analysis period (R2 4.3): the six period settings as one control. A year strip of twelve months with a start and an end date
// handle, an hour strip of 0 to 23 h with a start and an end hour handle, each handle with its value in a bubble over it ("21 Dec",
// "10 h"), and a row of presets that set the dates and keep the hours. The strips are drawn by ScaleStrip, which the balance
// temperature shares.
//
// A start after the end is drawn wrapped: dates across the new year, hours across midnight. Every change goes through
// withOvernightHoursOnOneDateAsOneNight (analysis_period.ts), so hours across midnight on one date are one night. A period stored
// as one date with hours across midnight (a hand-edited config, an older save) is shown as the engine runs it: the whole year on the
// year strip, and a note under the strips that starts "Every day, 22 to 2 h", as the step summary reads; it is not changed until the
// next change in the control. A period not set yet says so in the same place.
//
// How changes are sent: a key or a preset is one change; a drag is held here and sent once, on release, so a value on the way (a
// drag that crosses the end hour and comes back) never moves the end date. The form saves once the changes stop.
//
// In Solar usefulness a fifth preset, "Cold period from the weather file", sets the dates of the weather file's cold period
// (steps/cold_period_request.ts). What it found, or why it cannot be used yet, is the preset's tooltip (on hover and keyboard focus,
// as the mode tiles show theirs) and its description for a screen reader. The heating season preset follows the hemisphere of the
// weather file: October to April in the north, April to October in the south.
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { messages } from "../../messages";
import {
  changedPeriodSettings, dateHandleValueAfterKey, dateRangeSegments, dayOfYearAt, daysInMonth, DAYS_IN_YEAR, handlePositionOf, handleValueOf,
  datesMatch, hourAt, hourHandleValueAfterKey, hourRangeSegments, HOURS_IN_DAY, monthDayOf, PERIOD_PRESETS, periodFromSettings, periodInWords,
  periodWithDates, periodWithHandleAt, presetMatches, presetPeriod, runsEveryNightOfTheYear, withOvernightHoursOnOneDateAsOneNight,
  type AnalysisPeriodField, type ColdPeriodState, type Hemisphere, type Period, type PeriodDates, type PeriodPreset, type PeriodHandle,
} from "../analysis_period";
import { placedTooltipStyle, placementUnder, type TooltipPlacement } from "../SettingTooltip";
import type { ControlProps } from "./NumberInput";
import { ScaleStrip, type ScaleStripHandle } from "./ScaleStrip";

export type { AnalysisPeriodField } from "../analysis_period";

interface AnalysisPeriodProps extends ControlProps {
  values: Record<AnalysisPeriodField, number | null>;
  onChange: (values: Partial<Record<AnalysisPeriodField, number | null>>) => void;
  /** The cold period of the weather file, for its preset; null in the modes without one. */
  coldPeriod?: ColdPeriodState | null;
  /** The hemisphere of the weather file, for the heating season preset; northern without a weather file. */
  hemisphere?: Hemisphere;
}

/** The name of a preset's button: the heating season names its months, which follow the hemisphere. */
function presetNameIn(preset: PeriodPreset, hemisphere: Hemisphere): string {
  return preset === "heating_season" && hemisphere === "southern" ? messages.southernHeatingSeasonPresetName : messages.periodPresetNames[preset];
}

/** What the cold period preset says about the cold period: what it found, or why it cannot be used yet. */
function coldPeriodLine(coldPeriod: ColdPeriodState): string {
  switch (coldPeriod.kind) {
    case "needs_weather_file": return messages.coldPeriodNeedsWeatherFile;
    case "finding": return messages.coldPeriodFinding;
    case "found": {
      const { startDay, startMonth, endDay, endMonth } = coldPeriod.dates;
      return messages.coldPeriodFound(startDay, startMonth, endDay, endMonth, messages.temperatureText(coldPeriod.baseTemperature));
    }
    case "none": return messages.coldPeriodNone(messages.temperatureText(coldPeriod.baseTemperature));
    case "failed": return messages.coldPeriodFailed(coldPeriod.reason);
  }
}

// Where a handle is drawn while the period is not set yet (the note says so): the whole year, every hour.
const WHOLE_YEAR_EVERY_HOUR: Period = { startMonth: 1, startDay: 1, startHour: 0, endMonth: 12, endDay: 31, endHour: 23 };

const isHourHandle = (handle: PeriodHandle) => handle === "start_hour" || handle === "end_hour";

/** A handle of a strip as ScaleStrip draws it: it says "21 December" or "10 h", its bubble shows "21 Dec" or "10 h". */
function stripHandleOf(period: Period, handle: PeriodHandle, id?: string): ScaleStripHandle<PeriodHandle> {
  const value = handleValueOf(period, handle);
  const { month, day } = monthDayOf(value);
  return {
    name: handle, id, position: handlePositionOf(period, handle), accessibleName: messages.periodHandleNames[handle], valueNow: value,
    spokenValue: isHourHandle(handle) ? messages.periodHourSpoken(value) : messages.periodDateSpoken(month, day),
    bubbleText: isHourHandle(handle) ? messages.periodHourSpoken(value) : messages.periodDateOnBubble(month, day),
  };
}

const MONTH_CELLS = messages.monthInitials.map((initial, index) => ({ label: initial, length: daysInMonth(index + 1) }));
const HOUR_CELLS = Array.from({ length: HOURS_IN_DAY }, (_, hour) => ({ label: hour % 6 === 0 ? String(hour) : "", length: 1 }));

export function AnalysisPeriod({ values, onChange, inputId, labelId, invalid, describedBy, disabled, coldPeriod = null,
                                 hemisphere = "northern" }: AnalysisPeriodProps) {
  const stored = periodFromSettings(values);
  const current = stored ?? WHOLE_YEAR_EVERY_HOUR;
  // The period of a drag, as dragged (the end date of one night is applied to what is shown and sent, not kept), else null.
  // Otherwise the stored period is shown as it is.
  const [draggedPeriod, setDraggedPeriod] = useState<Period | null>(null);
  const draggedPeriodNow = useRef<Period | null>(null);
  const shown = draggedPeriod === null ? current : withOvernightHoursOnOneDateAsOneNight(draggedPeriod);

  const send = (next: Period) => {
    const changes = changedPeriodSettings(values, withOvernightHoursOnOneDateAsOneNight(next));
    if (Object.keys(changes).length > 0) onChange(changes);
  };
  const strip = {
    invalid, describedBy, disabled,
    onDragMove: (handle: PeriodHandle, value: number) => {
      draggedPeriodNow.current = periodWithHandleAt(draggedPeriodNow.current ?? current, handle, value);
      setDraggedPeriod(draggedPeriodNow.current);
    },
    onDragEnd: () => {
      const dragged = draggedPeriodNow.current;
      draggedPeriodNow.current = null;
      setDraggedPeriod(null);
      if (dragged !== null) send(dragged);
    },
    onKey: (handle: PeriodHandle, key: string) => {
      const value = (isHourHandle(handle) ? hourHandleValueAfterKey : dateHandleValueAfterKey)(handleValueOf(current, handle), key);
      if (value === null) return null;
      send(periodWithHandleAt(current, handle, value));
      return handle;
    },
  };
  const noteUnderStrips = stored === null ? messages.periodNotSet
    : runsEveryNightOfTheYear(stored) ? messages.periodRunsEveryDay(periodInWords(stored)) : null;

  return (
    <div role="group" aria-labelledby={labelId} className="period-control">
      <ScaleStrip {...strip} handles={[stripHandleOf(shown, "start_date", inputId), stripHandleOf(shown, "end_date")]} segments={dateRangeSegments(shown)}
                  valueAt={dayOfYearAt} valueRange={[1, DAYS_IN_YEAR]} cells={MONTH_CELLS} />
      <ScaleStrip {...strip} handles={[stripHandleOf(shown, "start_hour"), stripHandleOf(shown, "end_hour")]} segments={hourRangeSegments(shown)}
                  valueAt={hourAt} valueRange={[0, HOURS_IN_DAY - 1]} cells={HOUR_CELLS} />
      {noteUnderStrips !== null && <p className="setting-note">{noteUnderStrips}</p>}
      <div role="group" aria-label={messages.periodPresets} className="period-presets">
        {PERIOD_PRESETS.map((preset) => (
          <button key={preset} type="button" className="period-preset" disabled={disabled} aria-pressed={stored !== null && presetMatches(preset, current, hemisphere)}
                  onClick={() => send(presetPeriod(preset, current, hemisphere))}>
            {presetNameIn(preset, hemisphere)}
          </button>
        ))}
        {coldPeriod !== null && (
          <ColdPeriodPreset coldPeriod={coldPeriod} disabled={disabled}
                            pressed={stored !== null && coldPeriod.kind === "found" && datesMatch(current, coldPeriod.dates)}
                            onUse={(dates) => send(periodWithDates(current, dates))} />
        )}
      </div>
    </div>
  );
}

interface ColdPeriodPresetProps {
  coldPeriod: ColdPeriodState;
  pressed: boolean;
  disabled: boolean;
  onUse: (dates: PeriodDates) => void;
}

/**
 * The cold period preset and its tooltip, which holds what it found or why it cannot be used yet. The tooltip shows while the
 * pointer is over the button or the keyboard focus is on it (the focus a pointer press gives it does not count), and Escape closes
 * it; it lets the pointer through, so it never takes a click. A screen reader reads the same text as the button's description, a
 * status region, so a change (the cold period found) is announced.
 */
function ColdPeriodPreset({ coldPeriod, pressed, disabled, onUse }: ColdPeriodPresetProps) {
  const [hovered, setHovered] = useState(false);
  const [keyboardFocused, setKeyboardFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);     // Escape closes the tooltip while the pointer or the focus is still there
  const [placement, setPlacement] = useState<TooltipPlacement | null>(null);
  // A pointer press is under way: the focus it gives the button is not the keyboard's, and opens no tooltip. A touch focuses the
  // button before its click, so the press ends with the click, or when the focus leaves.
  const pointerPressing = useRef(false);
  const button = useRef<HTMLButtonElement>(null);
  const tooltip = useRef<HTMLSpanElement>(null);
  const descriptionId = useId();
  const open = (hovered || keyboardFocused) && !dismissed;
  const line = coldPeriodLine(coldPeriod);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDismissed(true);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  useLayoutEffect(() => {
    setPlacement(null);
    if (!open) return;
    const place = () => {
      if (button.current && tooltip.current) setPlacement(placementUnder(button.current, tooltip.current));
    };
    place();
    window.addEventListener("scroll", place, true);     // capture: the panel's own scrolling moves the button too
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  return (
    <span className="period-preset-anchor" onMouseEnter={() => { setHovered(true); setDismissed(false); }} onMouseLeave={() => setHovered(false)}>
      {/* Not ready yet: aria-disabled, not disabled, so the button stays in the tab order and its description is read with it. */}
      <button ref={button} type="button" className="period-preset" disabled={disabled} aria-disabled={coldPeriod.kind !== "found" || undefined}
              aria-describedby={descriptionId} aria-pressed={pressed}
              onPointerDown={() => { pointerPressing.current = true; }}
              onFocus={() => {
                if (pointerPressing.current) return;
                setKeyboardFocused(true);
                setDismissed(false);
              }}
              onBlur={() => { setKeyboardFocused(false); pointerPressing.current = false; }}
              onClick={() => {
                pointerPressing.current = false;
                if (coldPeriod.kind === "found") onUse(coldPeriod.dates);
              }}>
        {messages.coldPeriodPreset}
      </button>
      <span id={descriptionId} className="visually-hidden" role="status">{line}</span>
      {open && (
        // Seen, not read: a screen reader has the same text as the button's description.
        <span ref={tooltip} role="tooltip" aria-hidden="true" className="setting-tooltip period-preset-tooltip" style={placedTooltipStyle(placement)}>
          {line}
        </span>
      )}
    </span>
  );
}
