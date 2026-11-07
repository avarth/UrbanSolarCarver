// The panel of the sun tool, under the view's toolbar in every workspace (user, 2026-11-07), opened and closed by the toolbar's sun
// button. Open, the view shows the year's sun path; a switch chooses Sun path only or Shadows at a time: a moment, one day on a year
// strip (with the equinoxes and the solstices as presets) and one time on a day strip, each strip with a single handle, and where the
// sun stands then; and at the end the clock the times are read in. The strips are the criteria panel's (ScaleStrip). Without a
// weather file the panel says one is needed. The 3D view draws what it sets (use_sun_study, the sun_study layer, sun_shading). The
// hours of sun over a period are a Sun hours study in Simulate.
import { useId, useRef, useState } from "react";
import { messages } from "../messages";
import { formattedNumber } from "../format_numbers";
import { dateHandleValueAfterKey, dayOfYear, dayOfYearAt, DAYS_IN_YEAR, daysInMonth, monthDayOf } from "../settings_form/analysis_period";
import { ScaleStrip, type ScaleStripCell } from "../settings_form/widgets/ScaleStrip";
import { clockText, MINUTES_PER_DAY, SUN_VIEWS, TIME_BASES, TIME_STEP_MINUTES, type MonthDay, type SunStudyHook } from "./use_sun_study";
import "../settings_form/settings_form.css";
import "./simulate.css";

const KEY_DAYS: readonly MonthDay[] = [{ month: 3, day: 21 }, { month: 6, day: 21 }, { month: 9, day: 21 }, { month: 12, day: 21 }];
const MONTH_CELLS: ScaleStripCell[] = messages.monthInitials.map((initial, index) => ({ label: initial, length: daysInMonth(index + 1) }));
const HOUR_CELLS: ScaleStripCell[] = Array.from({ length: 24 }, (_, hour) => ({ label: hour % 6 === 0 ? String(hour) : "", length: 1 }));
const LAST_MINUTE = MINUTES_PER_DAY - TIME_STEP_MINUTES;
const holdTo = (value: number, lowest: number, highest: number) => Math.min(Math.max(value, lowest), highest);

/** Where a key moves the time: arrows 5 minutes, Page Up and Page Down an hour, Home and End the day's ends. */
export function minuteAfterKey(minute: number, key: string): number | null {
  switch (key) {
    case "ArrowRight": case "ArrowUp": return holdTo(minute + TIME_STEP_MINUTES, 0, LAST_MINUTE);
    case "ArrowLeft": case "ArrowDown": return holdTo(minute - TIME_STEP_MINUTES, 0, LAST_MINUTE);
    case "PageUp": return holdTo(minute + 60, 0, LAST_MINUTE);
    case "PageDown": return holdTo(minute - 60, 0, LAST_MINUTE);
    case "Home": return 0;
    case "End": return LAST_MINUTE;
    default: return null;
  }
}

/** The time under the pointer, *fraction* of the way along the day strip, in 5 minute steps. */
export function minuteAt(fraction: number): number {
  return holdTo(Math.floor((fraction * MINUTES_PER_DAY) / TIME_STEP_MINUTES) * TIME_STEP_MINUTES, 0, LAST_MINUTE);
}

/** A strip with one handle: *value* shown while dragged, sent with *onChange* at the release (and at each key). */
function SingleStrip({ name, label, value, position, bubble, spoken, cells, valueAt, valueRange, keyStep, onChange, live }: {
  name: string; label: string; value: number; position: (value: number) => number; bubble: (value: number) => string; spoken: (value: number) => string;
  cells: ScaleStripCell[]; valueAt: (fraction: number) => number; valueRange: [number, number]; keyStep: (value: number, key: string) => number | null;
  onChange: (value: number) => void; live: boolean;
}) {
  const [dragged, setDragged] = useState<number | null>(null);
  const draggedNow = useRef<number | null>(null);
  const shown = dragged ?? value;
  return (
    <ScaleStrip handles={[{ name, position: position(shown), accessibleName: label, valueNow: shown, spokenValue: spoken(shown), bubbleText: bubble(shown) }]}
                segments={[]} cells={cells} valueAt={valueAt} valueRange={valueRange} invalid={false} describedBy={undefined} disabled={false}
                onDragMove={(_handle, next) => {
                  draggedNow.current = next;
                  setDragged(next);
                  if (live) onChange(next);
                }}
                onDragEnd={() => {
                  const next = draggedNow.current;
                  draggedNow.current = null;
                  setDragged(null);
                  if (next !== null) onChange(next);
                }}
                onKey={(handle, key) => {
                  const next = keyStep(value, key);
                  if (next === null) return null;
                  onChange(next);
                  return handle;
                }} />
  );
}

export function SunPanel({ sunStudy }: { sunStudy: SunStudyHook }) {
  const titleId = useId();
  const { settings, change, sunNow } = sunStudy;
  const day = dayOfYear(settings.date.month, settings.date.day);
  return (
    <section className="viewer-overlay sun-panel" aria-labelledby={titleId}>
      <div className="sun-panel-header">
        <h2 id={titleId} className="sun-panel-title">{messages.sunToolTitle}</h2>
        <button type="button" className="sun-panel-close" aria-label={messages.sunToolClose} title={messages.sunToolClose}
                onClick={() => change({ open: false })}>
          <span aria-hidden="true">×</span>
        </button>
      </div>
      {(
        <div className="sun-panel-body">
          {!sunStudy.available ? <p className="sun-panel-note">{messages.sunToolNoWeatherFile}</p> : (
            <>
              <div className="segmented-switch sun-panel-views" role="group" aria-label={messages.sunToolShow}>
                {SUN_VIEWS.map((view) => (
                  <button key={view} type="button" aria-pressed={settings.view === view} onClick={() => change({ view })}>{messages.sunToolViews[view]}</button>
                ))}
              </div>
              {(
                <div className="sun-panel-moment" role="group" aria-label={messages.sunToolMoment}>
                  <span className="sun-panel-label">{messages.sunToolDay}</span>
                  <SingleStrip name="day" label={messages.sunToolDay} value={day} position={(value) => (value - 0.5) / DAYS_IN_YEAR}
                               bubble={(value) => { const { month, day: dayOfMonth } = monthDayOf(value); return messages.periodDateOnBubble(month, dayOfMonth); }}
                               spoken={(value) => { const { month, day: dayOfMonth } = monthDayOf(value); return messages.periodDateSpoken(month, dayOfMonth); }}
                               cells={MONTH_CELLS} valueAt={dayOfYearAt} valueRange={[1, DAYS_IN_YEAR]} keyStep={dateHandleValueAfterKey}
                               onChange={(value) => change({ date: monthDayOf(value) })} live={false} />
                  <div className="period-presets" role="group" aria-label={messages.sunToolKeyDays}>
                    {KEY_DAYS.map((keyDay) => (
                      <button key={`${keyDay.month}-${keyDay.day}`} type="button" className="period-preset"
                              aria-pressed={settings.date.month === keyDay.month && settings.date.day === keyDay.day} onClick={() => change({ date: keyDay })}>
                        {messages.sunToolDayName(keyDay.day, keyDay.month)}
                      </button>
                    ))}
                  </div>
                  <span className="sun-panel-label">{messages.sunToolTime}</span>
                  <SingleStrip name="time" label={messages.sunToolTime} value={settings.minute} position={(value) => (value + TIME_STEP_MINUTES / 2) / MINUTES_PER_DAY}
                               bubble={clockText} spoken={clockText} cells={HOUR_CELLS} valueAt={minuteAt} valueRange={[0, LAST_MINUTE]} keyStep={minuteAfterKey}
                               onChange={(minute) => change({ minute })} live />
                  <p className="sun-panel-note" role="status">
                    {sunNow === null ? messages.sunToolBelowHorizon
                      : messages.sunToolSunAt(formattedNumber(Math.round(sunNow.altitude)), formattedNumber(Math.round(sunNow.azimuth)))}
                  </p>
                </div>
              )}
              <label className="sun-panel-row sun-panel-clock">
                <span className="sun-panel-label">{messages.sunToolClock}</span>
                <select value={settings.timeBasis} onChange={(event) => change({ timeBasis: event.target.value as typeof settings.timeBasis })}>
                  {TIME_BASES.map((basis) => <option key={basis} value={basis}>{messages.sunToolTimeBases[basis]}</option>)}
                </select>
              </label>
            </>
          )}
        </div>
      )}
    </section>
  );
}
