// Simulate's sun tool (user, 2026-10-28: the traditional study of a project's massing with the sun): the clock the times are read in,
// the year's sun path with a day, and one of two views, never both: the shadows at a moment (a day and a time), or the hours in shade
// over a period (days and hours, as the analysis period gives them). The Sun panel sets them and the 3D view draws them. It reads
// GET sun-chart and sun-positions while Simulate is open and the project has a weather file.
import { useEffect, useMemo, useState } from "react";
import { ApiError, getSunChart, getSunPositions, serviceProblemOf, type SunChart, type SunPosition, type SunPositions } from "../api_client/client";
import { dayAndMonth, messages } from "../messages";
import type { AnalysisPeriodField } from "../settings_form/analysis_period";
import type { Point3 } from "../viewer/local_origin";
import { sunAt, type ShadeHours, type ShadePalette } from "../viewer/sun_study";

const NOT_FOUND = 404;
// The sun of the day is read every 5 minutes; the time strip moves in the same steps.
export const TIME_STEP_MINUTES = 5;
// The hours in shade are counted every 10 minutes on one day, every 30 over several days (sampled on fewer days when long).
const SHADE_STEP_MINUTES_OF_A_DAY = 10;
const SHADE_STEP_MINUTES_OF_DAYS = 30;
export const MINUTES_PER_DAY = 24 * 60;

export interface MonthDay {
  month: number;
  day: number;
}

/** The clock the times are read in: the weather file's local standard time, daylight saving time (an hour ahead), true solar time. */
export type TimeBasis = "standard" | "solar" | "daylight_saving";
export const TIME_BASES: readonly TimeBasis[] = ["standard", "solar", "daylight_saving"];

/** What the view shows besides the sun path: nothing, the shadows at a moment, or the hours in shade over a period. */
export type SunView = "none" | "shadows" | "shade";
export const SUN_VIEWS: readonly SunView[] = ["none", "shadows", "shade"];

export type ShadePeriod = Record<AnalysisPeriodField, number>;

export interface SunStudySettings {
  timeBasis: TimeBasis;
  showPath: boolean;
  view: SunView;
  /** The moment: the day of the sun path and of the shadows, and the time (minute of the day). */
  date: MonthDay;
  minute: number;
  /** The period of the hours in shade: its days, and its hours with the end hour counted (8 to 15 h is 08:00 to 16:00). */
  period: ShadePeriod;
  palette: ShadePalette;
}

/** What the 3D view draws of the sun tool. */
export interface SunStudyView {
  chart: SunChart | null;
  sun: Point3 | null;
  shadows: boolean;
  shade: (ShadeHours & { title: string }) | null;
}

export interface SunStudyHook {
  settings: SunStudySettings;
  change: (changes: Partial<SunStudySettings>) => void;
  /** The project has a weather file; without one the panel says so and nothing is read. */
  available: boolean;
  /** The sun at the moment; null below the horizon or while it is read. */
  sunNow: SunPosition | null;
  view: SunStudyView;
}

export const INITIAL_SUN_STUDY: SunStudySettings = {
  timeBasis: "standard", showPath: false, view: "none", date: { month: 12, day: 21 }, minute: 12 * 60,
  period: { start_month: 12, start_day: 21, start_hour: 8, end_month: 12, end_day: 21, end_hour: 15 }, palette: "viridis",
};

export const monthDayText = ({ month, day }: MonthDay) => `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
export const clockText = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;

/** The hours in shade the view counts from *positions*: each stands for its step, divided by the days sampled. */
export function shadeHoursOf(positions: SunPositions, maxHours: number, palette: ShadePalette): ShadeHours {
  return {
    directions: positions.positions.map((position) => position.vector as Point3),
    hoursEach: positions.step_minutes / 60 / Math.max(1, positions.days_sampled),
    maxHours, palette,
  };
}

/** The request of the hours in shade of *period*: each time is the middle of its step, so the count covers the hours and no more. */
export function shadeRequest(period: ShadePeriod, timeBasis: TimeBasis) {
  const from = monthDayText({ month: period.start_month, day: period.start_day });
  const to = monthDayText({ month: period.end_month, day: period.end_day });
  const step = from === to ? SHADE_STEP_MINUTES_OF_A_DAY : SHADE_STEP_MINUTES_OF_DAYS;
  const hours = ((period.end_hour - period.start_hour + 24) % 24) + 1;      // over midnight when the end hour comes first
  const start = period.start_hour * 60 + step / 2;
  const end = (((period.end_hour + 1) * 60 - step / 2) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  return { range: { from, to, start, end, step, time_basis: timeBasis }, hours };
}

interface SunStudySource {
  token: string;
  project: string;
  /** Simulate is open: the sun is read only then. */
  active: boolean;
  hasWeatherFile: boolean;
  onServiceProblem: (error: unknown) => void;
}

export function useSunStudy({ token, project, active, hasWeatherFile, onServiceProblem }: SunStudySource): SunStudyHook {
  const [settings, setSettings] = useState<SunStudySettings>(INITIAL_SUN_STUDY);
  const change = (changes: Partial<SunStudySettings>) => setSettings((current) => ({ ...current, ...changes }));
  const [chart, setChart] = useState<{ key: string; chart: SunChart } | null>(null);
  const [day, setDay] = useState<{ key: string; positions: SunPosition[] } | null>(null);
  const [shadePositions, setShadePositions] = useState<{ key: string; positions: SunPositions } | null>(null);
  const reads = active && hasWeatherFile;
  const { timeBasis, view, period } = settings;
  const report = (error: unknown) => {
    if (!(error instanceof ApiError && error.status === NOT_FOUND) && serviceProblemOf(error) !== "other") onServiceProblem(error);
  };

  // The sun path's day: the moment's, or the first day of the period while the hours in shade are shown.
  const date = monthDayText(view === "shade" ? { month: period.start_month, day: period.start_day } : settings.date);
  const chartKey = `${date} ${timeBasis}`;
  useEffect(() => {
    if (!reads || !settings.showPath) return;
    let wanted = true;
    getSunChart(token, project, date, timeBasis).then((reply) => { if (wanted) setChart({ key: chartKey, chart: reply }); }).catch(report);
    return () => { wanted = false; };
  }, [reads, settings.showPath, chartKey]);

  const momentDate = monthDayText(settings.date);
  const dayKey = `${momentDate} ${timeBasis}`;
  useEffect(() => {
    if (!reads) return;
    let wanted = true;
    getSunPositions(token, project, { from: momentDate, to: momentDate, start: 0, end: MINUTES_PER_DAY, step: TIME_STEP_MINUTES, time_basis: timeBasis })
      .then((reply) => { if (wanted) setDay({ key: dayKey, positions: reply.positions }); }).catch(report);
    return () => { wanted = false; };
  }, [reads, dayKey]);

  const shade = shadeRequest(period, timeBasis);
  const shadeKey = JSON.stringify(shade.range);
  const shadeWanted = reads && view === "shade";
  useEffect(() => {
    if (!shadeWanted) return;
    let wanted = true;
    getSunPositions(token, project, shade.range).then((reply) => { if (wanted) setShadePositions({ key: shadeKey, positions: reply }); }).catch(report);
    return () => { wanted = false; };
  }, [shadeWanted, shadeKey]);

  const sunNow = reads && day?.key === dayKey ? sunAt(day.positions, settings.minute, TIME_STEP_MINUTES / 2) : null;
  const shownShade = shadeWanted && shadePositions?.key === shadeKey ? shadePositions.positions : null;
  // The count once per set of positions; another palette only recolours it (the view does not count again).
  const counted = useMemo(() => {
    if (shownShade === null) return null;
    const { from, to } = shade.range;
    const days = from === to ? dayAndMonth(from) : messages.sunToolDays(dayAndMonth(from), dayAndMonth(to), shownShade.day_step);
    const end = clockText(((period.end_hour + 1) % 24) * 60);
    return { ...shadeHoursOf(shownShade, shade.hours, INITIAL_SUN_STUDY.palette),
             title: messages.shadeHoursLegend(clockText(period.start_hour * 60), end, days) };
  }, [shownShade]);
  const shadeView = useMemo(() => (counted === null ? null : { ...counted, palette: settings.palette }), [counted, settings.palette]);
  const sunVector = view === "shade" || sunNow === null ? null : (sunNow.vector as Point3);
  const sunKey = sunVector?.join(",") ?? "";
  const shownView = useMemo<SunStudyView>(() => ({
    chart: reads && settings.showPath && chart?.key === chartKey ? chart.chart : null,
    sun: reads ? sunVector : null,
    shadows: reads && view === "shadows",
    shade: reads && view === "shade" ? shadeView : null,
  }), [reads, settings.showPath, view, chart, chartKey, sunKey, shadeView]);

  return { settings, change, available: hasWeatherFile, sunNow, view: shownView };
}
