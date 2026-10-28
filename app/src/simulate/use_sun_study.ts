// Simulate's sun tool (user, 2026-10-28: the traditional study of a project's massing with the sun): the day and time chosen, the
// year's sun path with that day, the shadows at that time, and the hours in shade over a range of times, as the Sun panel sets them
// and the 3D view draws them. It reads GET sun-chart and sun-positions while Simulate is open and the project has a weather file;
// the times are the weather file's local standard time.
import { useEffect, useMemo, useState } from "react";
import { ApiError, getSunChart, getSunPositions, serviceProblemOf, type SunChart, type SunPosition, type SunPositions } from "../api_client/client";
import { dayAndMonth, messages } from "../messages";
import type { Point3 } from "../viewer/local_origin";
import { sunAt, type ShadeHours } from "../viewer/sun_study";

const NOT_FOUND = 404;
// The sun of the day is read every 5 minutes; the time slider moves in the same steps.
export const TIME_STEP_MINUTES = 5;
// The hours in shade are counted every 10 minutes on one day, every 30 over several days (sampled on fewer days when long).
const SHADE_STEP_MINUTES_OF_A_DAY = 10;
const SHADE_STEP_MINUTES_OF_DAYS = 30;
export const MINUTES_PER_DAY = 24 * 60;

export interface MonthDay {
  month: number;
  day: number;
}

export interface SunStudySettings {
  date: MonthDay;
  /** Minute of the day, local standard time. */
  minute: number;
  showPath: boolean;
  shadows: boolean;
  shade: boolean;
  shadeStartMinute: number;
  shadeEndMinute: number;
  /** The last day of the hours in shade; null: the chosen day alone. */
  shadeUntil: MonthDay | null;
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
  /** The sun at the chosen time; null below the horizon or while it is read. */
  sunNow: SunPosition | null;
  view: SunStudyView;
}

export const INITIAL_SUN_STUDY: SunStudySettings = {
  date: { month: 12, day: 21 }, minute: 12 * 60, showPath: false, shadows: false, shade: false,
  shadeStartMinute: 8 * 60, shadeEndMinute: 16 * 60, shadeUntil: null,
};

export const monthDayText = ({ month, day }: MonthDay) => `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
export const clockText = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;

/** The hours in shade the view counts from *positions*: each stands for *stepMinutes*, divided by the days sampled. */
export function shadeHoursOf(positions: SunPositions, startMinute: number, endMinute: number): ShadeHours {
  return {
    directions: positions.positions.map((position) => position.vector as Point3),
    hoursEach: positions.step_minutes / 60 / Math.max(1, positions.days_sampled),
    maxHours: (endMinute - startMinute) / 60,
  };
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
  const [chart, setChart] = useState<{ date: string; chart: SunChart } | null>(null);
  const [day, setDay] = useState<{ date: string; positions: SunPosition[] } | null>(null);
  const [shadePositions, setShadePositions] = useState<{ key: string; positions: SunPositions } | null>(null);
  const reads = active && hasWeatherFile;
  const date = monthDayText(settings.date);
  const report = (error: unknown) => {
    if (!(error instanceof ApiError && error.status === NOT_FOUND) && serviceProblemOf(error) !== "other") onServiceProblem(error);
  };

  useEffect(() => {
    if (!reads || !settings.showPath) return;
    let wanted = true;
    getSunChart(token, project, date).then((reply) => { if (wanted) setChart({ date, chart: reply }); }).catch(report);
    return () => { wanted = false; };
  }, [reads, settings.showPath, date]);

  useEffect(() => {
    if (!reads) return;
    let wanted = true;
    getSunPositions(token, project, { from: date, to: date, start: 0, end: MINUTES_PER_DAY, step: TIME_STEP_MINUTES })
      .then((reply) => { if (wanted) setDay({ date, positions: reply.positions }); }).catch(report);
    return () => { wanted = false; };
  }, [reads, date]);

  // The hours in shade: each time stands for the middle of its step, so the count covers the range and no more.
  const until = settings.shadeUntil === null ? date : monthDayText(settings.shadeUntil);
  const step = settings.shadeUntil === null ? SHADE_STEP_MINUTES_OF_A_DAY : SHADE_STEP_MINUTES_OF_DAYS;
  const shadeRange = { from: date, to: until, start: settings.shadeStartMinute + step / 2, end: settings.shadeEndMinute - step / 2, step };
  const shadeKey = JSON.stringify(shadeRange);
  const shadeWanted = reads && settings.shade && settings.shadeEndMinute > settings.shadeStartMinute;
  useEffect(() => {
    if (!shadeWanted) return;
    let wanted = true;
    getSunPositions(token, project, shadeRange).then((reply) => { if (wanted) setShadePositions({ key: shadeKey, positions: reply }); }).catch(report);
    return () => { wanted = false; };
  }, [shadeWanted, shadeKey]);

  const sunNow = reads && day?.date === date ? sunAt(day.positions, settings.minute, TIME_STEP_MINUTES / 2) : null;
  const shownShade = shadeWanted && shadePositions?.key === shadeKey ? shadePositions.positions : null;
  const shade = useMemo(() => {
    if (shownShade === null) return null;
    const days = settings.shadeUntil === null ? dayAndMonth(date)
      : messages.sunToolDays(dayAndMonth(date), dayAndMonth(until), shownShade.day_step);
    return { ...shadeHoursOf(shownShade, settings.shadeStartMinute, settings.shadeEndMinute),
             title: messages.shadeHoursLegend(clockText(settings.shadeStartMinute), clockText(settings.shadeEndMinute), days) };
  }, [shownShade]);
  const sunVector = sunNow === null ? null : (sunNow.vector as Point3);
  const sunKey = sunVector?.join(",") ?? "";
  const view = useMemo<SunStudyView>(() => ({
    chart: reads && settings.showPath && chart?.date === date ? chart.chart : null,
    sun: sunVector,
    shadows: reads && settings.shadows,
    shade: reads ? shade : null,
  }), [reads, settings.showPath, settings.shadows, chart, date, sunKey, shade]);

  return { settings, change, available: hasWeatherFile, sunNow, view };
}
