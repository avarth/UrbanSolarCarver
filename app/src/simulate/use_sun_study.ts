// The sun tool (user, 2026-10-28: the traditional study of a project's massing with the sun; in every workspace since 2026-11-07):
// while it is open, the year's sun path with a day, and, chosen on a switch, the shadows at a moment (a day and a time), the times read
// in the clock chosen. The Sun panel sets them and the 3D view draws them; a closed tool draws nothing. It reads GET sun-chart and
// sun-positions while the tool is open and the project has a weather file. The hours of sun over a period are a Sun hours study.
import { useEffect, useEffectEvent, useMemo, useState } from "react";
import { ApiError, getSunChart, getSunPositions, reportServiceProblem, type SunChart, type SunPosition } from "../api_client/client";
import { useProjectSession } from "../api_client/project_session";
import type { Point3 } from "../viewer/local_origin";
import { sunAt, type SunStudyView } from "../viewer/sun_study";

const NOT_FOUND = 404;
// The sun of the day is read every 5 minutes; the time strip moves in the same steps.
export const TIME_STEP_MINUTES = 5;
export const MINUTES_PER_DAY = 24 * 60;

export interface MonthDay {
  month: number;
  day: number;
}

/** The clock the times are read in: the weather file's local standard time, daylight saving time (an hour ahead), true solar time. */
export type TimeBasis = "standard" | "solar" | "daylight_saving";
export const TIME_BASES: readonly TimeBasis[] = ["standard", "solar", "daylight_saving"];

/** What the view shows besides the sun path: nothing, or the shadows at a moment. */
export type SunView = "none" | "shadows";
export const SUN_VIEWS: readonly SunView[] = ["none", "shadows"];

export interface SunStudySettings {
  timeBasis: TimeBasis;
  /** The sun tool is open: the sun path and the view are drawn (user, 2026-10-28: opening the tool shows them). */
  open: boolean;
  view: SunView;
  /** The moment: the day of the sun path and of the shadows, and the time (minute of the day). */
  date: MonthDay;
  minute: number;
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
  timeBasis: "standard", open: false, view: "none", date: { month: 12, day: 21 }, minute: 12 * 60,
};

export const monthDayText = ({ month, day }: MonthDay) => `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
export const clockText = (minute: number) => `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;

interface SunStudySource {
  /** A project is open: the sun is read only then (and while the tool is open). */
  active: boolean;
  hasWeatherFile: boolean;
}

export function useSunStudy({ active, hasWeatherFile }: SunStudySource): SunStudyHook {
  const { token, project, onServiceProblem } = useProjectSession();
  const [settings, setSettings] = useState<SunStudySettings>(INITIAL_SUN_STUDY);
  const change = (changes: Partial<SunStudySettings>) => setSettings((current) => ({ ...current, ...changes }));
  const [chart, setChart] = useState<{ key: string; chart: SunChart } | null>(null);
  const [day, setDay] = useState<{ key: string; positions: SunPosition[] } | null>(null);
  const reads = active && hasWeatherFile && settings.open;
  const { timeBasis, view } = settings;
  const report = useEffectEvent((error: unknown) => {
    if (!(error instanceof ApiError && error.status === NOT_FOUND)) reportServiceProblem(error, onServiceProblem);
  });

  // The sun path's day: the moment's.
  const date = monthDayText(settings.date);
  const chartKey = `${date} ${timeBasis}`;
  useEffect(() => {
    if (!reads) return;
    let wanted = true;
    getSunChart(token, project, date, timeBasis).then((reply) => { if (wanted) setChart({ key: chartKey, chart: reply }); }).catch((error) => report(error));
    return () => { wanted = false; };
  }, [reads, token, project, date, timeBasis, chartKey]);

  const momentDate = monthDayText(settings.date);
  const dayKey = `${momentDate} ${timeBasis}`;
  useEffect(() => {
    if (!reads) return;
    let wanted = true;
    getSunPositions(token, project, { from: momentDate, to: momentDate, start: 0, end: MINUTES_PER_DAY, step: TIME_STEP_MINUTES, time_basis: timeBasis })
      .then((reply) => { if (wanted) setDay({ key: dayKey, positions: reply.positions }); }).catch((error) => report(error));
    return () => { wanted = false; };
  }, [reads, token, project, momentDate, timeBasis, dayKey]);

  const sunNow = reads && day?.key === dayKey ? sunAt(day.positions, settings.minute, TIME_STEP_MINUTES / 2) : null;
  // The same array while the same position of the day is shown: the positions are kept as read.
  const sunVector = sunNow === null ? null : (sunNow.vector as Point3);
  const shownView = useMemo<SunStudyView>(() => ({
    chart: reads && chart?.key === chartKey ? chart.chart : null,
    sun: reads ? sunVector : null,
    shadows: reads && view === "shadows",
  }), [reads, view, chart, chartKey, sunVector]);

  return { settings, change, available: hasWeatherFile, sunNow, view: shownView };
}
