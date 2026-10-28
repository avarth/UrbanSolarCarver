// The Sun panel of Simulate, under the studies panel and collapsible as it is: the day and the time, the year's sun path with that day,
// the shadows at that time, and the hours in shade over a range of hours on that day or over several days. Without a weather file it
// says one is needed. The 3D view draws what it sets (use_sun_study, the sun_study layer, sun_shading).
import { useId, useState } from "react";
import { messages } from "../messages";
import { formattedNumber } from "../steps/format_numbers";
import { clockText, MINUTES_PER_DAY, TIME_STEP_MINUTES, type MonthDay, type SunStudyHook } from "./use_sun_study";
import "./simulate.css";

const DAYS_OF_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const KEY_DAYS: readonly MonthDay[] = [{ month: 3, day: 21 }, { month: 6, day: 21 }, { month: 9, day: 21 }, { month: 12, day: 21 }];
const WHOLE_HOURS = Array.from({ length: 25 }, (_, hour) => hour);

/** The same day a month later (the last day of a shorter month; January after December): where "until" starts. */
function monthAfter({ month, day }: MonthDay): MonthDay {
  const next = (month % 12) + 1;
  return { month: next, day: Math.min(day, DAYS_OF_MONTH[next - 1]) };
}

function SunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="9" cy="9" r="3.2" />
      <path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.7 3.7l1.4 1.4M12.9 12.9l1.4 1.4M3.7 14.3l1.4-1.4M12.9 5.1l1.4-1.4" strokeLinecap="round" />
    </svg>
  );
}

function DayPicker({ value, label, onChange }: { value: MonthDay; label: string; onChange: (value: MonthDay) => void }) {
  return (
    <span className="sun-panel-day" role="group" aria-label={label}>
      <select aria-label={messages.sunToolMonth} value={value.month}
              onChange={(event) => { const month = Number(event.target.value); onChange({ month, day: Math.min(value.day, DAYS_OF_MONTH[month - 1]) }); }}>
        {messages.monthNames.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
      </select>
      <select aria-label={messages.sunToolDayOfMonth} value={value.day} onChange={(event) => onChange({ ...value, day: Number(event.target.value) })}>
        {Array.from({ length: DAYS_OF_MONTH[value.month - 1] }, (_, index) => <option key={index} value={index + 1}>{index + 1}</option>)}
      </select>
    </span>
  );
}

function HourPicker({ value, label, onChange }: { value: number; label: string; onChange: (minute: number) => void }) {
  return (
    <select aria-label={label} value={value} onChange={(event) => onChange(Number(event.target.value))}>
      {WHOLE_HOURS.map((hour) => <option key={hour} value={hour * 60}>{clockText(hour * 60)}</option>)}
    </select>
  );
}

export function SunPanel({ sunStudy }: { sunStudy: SunStudyHook }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const titleId = useId();
  const { settings, change, sunNow } = sunStudy;
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
              <div className="sun-panel-row">
                <span className="sun-panel-label">{messages.sunToolDay}</span>
                <DayPicker value={settings.date} label={messages.sunToolDay} onChange={(date) => change({ date })} />
              </div>
              <div className="sun-panel-key-days">
                {KEY_DAYS.map((day) => (
                  <button key={`${day.month}-${day.day}`} type="button" className="link-button"
                          aria-pressed={settings.date.month === day.month && settings.date.day === day.day} onClick={() => change({ date: day })}>
                    {messages.sunToolDayName(day.day, day.month)}
                  </button>
                ))}
              </div>
              <label className="sun-panel-row">
                <span className="sun-panel-label">{messages.sunToolTime}</span>
                <input type="range" min={0} max={MINUTES_PER_DAY - TIME_STEP_MINUTES} step={TIME_STEP_MINUTES} value={settings.minute}
                       aria-valuetext={clockText(settings.minute)} onChange={(event) => change({ minute: Number(event.target.value) })} />
                <output className="sun-panel-clock">{clockText(settings.minute)}</output>
              </label>
              <p className="sun-panel-note" role="status">
                {sunNow === null ? messages.sunToolBelowHorizon : messages.sunToolSunAt(formattedNumber(Math.round(sunNow.altitude)), formattedNumber(Math.round(sunNow.azimuth)))}
              </p>
              <label className="sun-panel-check">
                <input type="checkbox" checked={settings.showPath} onChange={(event) => change({ showPath: event.target.checked })} />
                {messages.sunToolPath}
              </label>
              <label className="sun-panel-check">
                <input type="checkbox" checked={settings.shadows} onChange={(event) => change({ shadows: event.target.checked })} />
                {messages.sunToolShadows}
              </label>
              <label className="sun-panel-check">
                <input type="checkbox" checked={settings.shade} onChange={(event) => change({ shade: event.target.checked })} />
                {messages.sunToolShade}
              </label>
              {settings.shade && (
                <div className="sun-panel-shade">
                  <div className="sun-panel-row">
                    <span className="sun-panel-label">{messages.sunToolFrom}</span>
                    <HourPicker value={settings.shadeStartMinute} label={messages.sunToolShadeStart} onChange={(shadeStartMinute) => change({ shadeStartMinute })} />
                    <span>{messages.sunToolTo}</span>
                    <HourPicker value={settings.shadeEndMinute} label={messages.sunToolShadeEnd} onChange={(shadeEndMinute) => change({ shadeEndMinute })} />
                  </div>
                  {settings.shadeEndMinute <= settings.shadeStartMinute && <p className="sun-panel-note">{messages.sunToolShadeRangeEmpty}</p>}
                  <label className="sun-panel-check">
                    <input type="checkbox" checked={settings.shadeUntil !== null}
                           onChange={(event) => change({ shadeUntil: event.target.checked ? monthAfter(settings.date) : null })} />
                    {messages.sunToolShadeUntil}
                  </label>
                  {settings.shadeUntil !== null && (
                    <DayPicker value={settings.shadeUntil} label={messages.sunToolShadeUntil} onChange={(shadeUntil) => change({ shadeUntil })} />
                  )}
                  <p className="sun-panel-note">{messages.sunToolShadeNote}</p>
                </div>
              )}
              <p className="sun-panel-note">{messages.sunToolStandardTime}</p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
