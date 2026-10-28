// The Sun panel of Simulate, under the studies panel and collapsible as it is (user, 2026-10-28). At the top the clock the times are
// read in and the year's sun path; then one of two views, never both, chosen on a switch, each with its own controls:
// - Shadows at a time: a moment, one day on a year strip (with the equinox and the solstices as presets) and one time on a day strip,
//   each strip with a single handle, and where the sun stands then;
// - Hours in shade: a period, the analysis period's control (a date range and an hour range, with its presets), and the colours of
//   the count, viridis or grey.
// The strips are the criteria panel's (ScaleStrip, AnalysisPeriod). Without a weather file the panel says one is needed. The 3D view
// draws what it sets (use_sun_study, the sun_study layer, sun_shading).
import { useId, useRef, useState } from "react";
import { messages } from "../messages";
import { formattedNumber } from "../steps/format_numbers";
import { dateHandleValueAfterKey, dayOfYear, dayOfYearAt, DAYS_IN_YEAR, daysInMonth, monthDayOf, type AnalysisPeriodField } from "../settings_form/analysis_period";
import { AnalysisPeriod } from "../settings_form/widgets/AnalysisPeriod";
import { ScaleStrip, type ScaleStripCell } from "../settings_form/widgets/ScaleStrip";
import { SHADE_PALETTES } from "../viewer/sun_study";
import { clockText, MINUTES_PER_DAY, SUN_VIEWS, TIME_BASES, TIME_STEP_MINUTES, type MonthDay, type SunStudyHook } from "./use_sun_study";
import "../settings_form/settings_form.css";
import "./simulate.css";

const KEY_DAYS: readonly MonthDay[] = [{ month: 3, day: 21 }, { month: 6, day: 21 }, { month: 9, day: 21 }, { month: 12, day: 21 }];
const MONTH_CELLS: ScaleStripCell[] = messages.monthInitials.map((initial, index) => ({ label: initial, length: daysInMonth(index + 1) }));
const HOUR_CELLS: ScaleStripCell[] = Array.from({ length: 24 }, (_, hour) => ({ label: hour % 6 === 0 ? String(hour) : "", length: 1 }));
const LAST_MINUTE = MINUTES_PER_DAY - TIME_STEP_MINUTES;
const holdTo = (value: number, lowest: number, highest: number) => Math.min(Math.max(value, lowest), highest);

function SunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="9" cy="9" r="3.2" />
      <path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.7 3.7l1.4 1.4M12.9 12.9l1.4 1.4M3.7 14.3l1.4-1.4M12.9 5.1l1.4-1.4" strokeLinecap="round" />
    </svg>
  );
}

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
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const titleId = useId();
  const periodLabelId = useId();
  const periodInputId = useId();
  const { settings, change, sunNow } = sunStudy;
  const day = dayOfYear(settings.date.month, settings.date.day);
  return (
    <section className={`sun-panel ${open ? "sun-panel-open" : "sun-panel-collapsed"}`} aria-labelledby={open ? titleId : undefined}
             aria-label={open ? undefined : messages.sunToolTitle}>
      <div className="sun-panel-header">
        <button type="button" className="sun-panel-toggle" aria-label={messages.sunToolTitle} aria-expanded={open}
                aria-controls={open ? bodyId : undefined} title={messages.sunToolTitle} onClick={() => setOpen((shown) => !shown)}>
          <SunIcon />
        </button>
        {open && <h2 id={titleId} className="sun-panel-title">{messages.sunToolTitle}</h2>}
      </div>
      {open && (
        <div id={bodyId} className="sun-panel-body">
          {!sunStudy.available ? <p className="sun-panel-note">{messages.sunToolNoWeatherFile}</p> : (
            <>
              <label className="sun-panel-row">
                <span className="sun-panel-label">{messages.sunToolClock}</span>
                <select value={settings.timeBasis} onChange={(event) => change({ timeBasis: event.target.value as typeof settings.timeBasis })}>
                  {TIME_BASES.map((basis) => <option key={basis} value={basis}>{messages.sunToolTimeBases[basis]}</option>)}
                </select>
              </label>
              <label className="sun-panel-check">
                <input type="checkbox" checked={settings.showPath} onChange={(event) => change({ showPath: event.target.checked })} />
                {messages.sunToolPath}
              </label>
              <div className="segmented-switch sun-panel-views" role="group" aria-label={messages.sunToolShow}>
                {SUN_VIEWS.map((view) => (
                  <button key={view} type="button" aria-pressed={settings.view === view} onClick={() => change({ view })}>{messages.sunToolViews[view]}</button>
                ))}
              </div>
              {settings.view !== "shade" ? (
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
              ) : (
                <div className="sun-panel-period">
                  <span id={periodLabelId} className="sun-panel-label">{messages.sunToolPeriod}</span>
                  <AnalysisPeriod values={settings.period} inputId={periodInputId} labelId={periodLabelId} invalid={false} describedBy={undefined} disabled={false}
                                  onChange={(changes) => change({ period: { ...settings.period, ...(changes as Partial<Record<AnalysisPeriodField, number>>) } })} />
                  <div className="sun-panel-row">
                    <span className="sun-panel-label">{messages.sunToolColours}</span>
                    <div className="segmented-switch" role="group" aria-label={messages.sunToolColours}>
                      {SHADE_PALETTES.map((palette) => (
                        <button key={palette} type="button" aria-pressed={settings.palette === palette} onClick={() => change({ palette })}>
                          {messages.shadePaletteNames[palette]}
                        </button>
                      ))}
                    </div>
                  </div>
                  <p className="sun-panel-note">{messages.sunToolShadeNote}</p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
