// The notice of a new weather file in the Settings step: a weather file added or replaced in this session (not one the project
// opened with) may call for another analysis period, and the notice offers it, with Keep beside it.
//
// In Solar usefulness the offer is the cold period of the new file (steps/cold_period_request.ts), once the answer for that file
// is in, where its dates differ from the period's; the hours are kept. In the other modes that read a period it is the period
// six months on, where the new file is in the other hemisphere from the one before (a project without one counts as northern:
// the starting values of the modes are northern). The notice is about the period the form showed when the file came: once that
// period changes, by the notice's button or by hand, it is gone.
import {
  datesMatch, periodShiftedBySixMonths, periodWithDates, type ColdPeriodState, type Hemisphere, type Period, type PeriodDates,
} from "../settings_form/analysis_period";
import { MODE_WITH_COLD_PERIOD } from "./cold_period_request";

/** A weather file added or replaced in this session. */
export interface WeatherFileChange {
  /** The weather file revision of the new file: the cold period answer the notice waits for is of this one. */
  weatherFileRevision: number;
  /** "<city>, <country>" of the new file; null without a LOCATION line. */
  location: string | null;
  /** The hemisphere of the weather file the project had last; northern when it had none. */
  previousHemisphere: Hemisphere;
  /** The hemisphere of the new file; null when its LOCATION line has no latitude the service can read. */
  newHemisphere: Hemisphere | null;
  /** The analysis period the form showed when the file came; null while one of its parts is not set or the mode reads none. */
  periodBefore: Period | null;
}

/** What the form shows now, as far as the notice reads it. */
export interface WeatherChangeSituation {
  mode: string;
  modeReadsPeriod: boolean;
  /** The analysis period the form shows; null while one of its parts is not set or the mode reads none. */
  period: Period | null;
  /** The cold period the page holds (useColdPeriod), and the weather file revision it is the answer for. */
  coldPeriod: ColdPeriodState | null;
  answeredWeatherFileRevision: number | null;
}

export type WeatherChangeSuggestion =
  | { kind: "cold_period"; location: string | null; coldDates: PeriodDates; current: Period; suggested: Period }
  | { kind: "six_months"; location: string; hemisphere: Hemisphere; suggested: Period };

const samePeriod = (first: Period, second: Period) =>
  (Object.keys(first) as (keyof Period)[]).every((part) => first[part] === second[part]);

/** The period the notice offers after *change*, or null when it shows nothing (yet). */
export function weatherChangeSuggestion(change: WeatherFileChange | null, situation: WeatherChangeSituation): WeatherChangeSuggestion | null {
  const { period, coldPeriod } = situation;
  if (change === null || change.periodBefore === null || period === null || !situation.modeReadsPeriod) return null;
  if (!samePeriod(period, change.periodBefore)) return null;
  if (situation.mode === MODE_WITH_COLD_PERIOD) {
    const answerOfNewFile = situation.answeredWeatherFileRevision === change.weatherFileRevision;
    if (!answerOfNewFile || coldPeriod?.kind !== "found" || datesMatch(period, coldPeriod.dates)) return null;
    return { kind: "cold_period", location: change.location, coldDates: coldPeriod.dates, current: period, suggested: periodWithDates(period, coldPeriod.dates) };
  }
  if (change.newHemisphere === null || change.location === null || change.newHemisphere === change.previousHemisphere) return null;
  return { kind: "six_months", location: change.location, hemisphere: change.newHemisphere, suggested: periodShiftedBySixMonths(period) };
}
