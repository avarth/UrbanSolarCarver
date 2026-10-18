// The analysis period (R2 4.3) as the control reads and changes it: dates in a year that is not a leap year (the engine checks the
// dates against one, pydantic_schemas.py _check_calendar_dates), the period in words, the presets, where a handle goes for a key
// or under the pointer, and the ranges the strips draw.
//
// The engine (Ladybug's AnalysisPeriod) takes a start after the end: dates across the new year (1 Oct to 30 Apr) and hours across
// midnight (22 to 2 h, the nights). Its one surprise is hours across midnight on one date: the start (21 Dec 22:00) is then after
// the end (21 Dec 02:00) and the period runs round the whole year, every night. The control never sends that: every change goes
// through withOvernightHoursOnOneDateAsOneNight, which makes it one night (21 to 22 Dec, 22 to 2 h).
import { messages } from "../messages";
import { ANALYSIS_PERIOD_FIELDS } from "./presentation";

export type AnalysisPeriodField = (typeof ANALYSIS_PERIOD_FIELDS)[number];

export interface Period {
  startMonth: number;
  startDay: number;
  startHour: number;
  endMonth: number;
  endDay: number;
  endHour: number;
}

/** One end of the period, for the typed fields: its date and hour. */
export type PeriodEnd = "start" | "end";

/** The four handles of the control: two on the year strip, two on the hour strip. */
export type PeriodHandle = "start_date" | "end_date" | "start_hour" | "end_hour";

const DAYS_IN_EACH_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
export const DAYS_IN_YEAR = 365;
export const HOURS_IN_DAY = 24;
const LAST_HOUR = HOURS_IN_DAY - 1;
// Page Up and Page Down on an hour handle (R2 4.3).
const HOURS_PER_PAGE = 6;

const holdTo = (value: number, lowest: number, highest: number) => Math.min(Math.max(value, lowest), highest);

export function daysInMonth(month: number): number {
  return DAYS_IN_EACH_MONTH[month - 1];
}

/** 1 January is 1, 31 December is 365. */
export function dayOfYear(month: number, day: number): number {
  return DAYS_IN_EACH_MONTH.slice(0, month - 1).reduce((total, days) => total + days, 0) + day;
}

/** The month and day of a day of the year (1 to 365). */
export function monthDayOf(day: number): { month: number; day: number } {
  let rest = holdTo(day, 1, DAYS_IN_YEAR);
  let month = 1;
  while (rest > daysInMonth(month)) {
    rest -= daysInMonth(month);
    month += 1;
  }
  return { month, day: rest };
}

/** "21 Dec, 10 to 14 h"; "1 Oct to 30 Apr, 0 to 23 h". */
export function periodInWords(period: Period): string {
  return messages.periodSummary(period.startMonth, period.startDay, period.startHour, period.endMonth, period.endDay, period.endHour);
}

/**
 * Hours across midnight on one date become one night: the end date is the day after the start date (31 December gives 1 January),
 * so the engine samples that night and not every night of the year. Anything else is left as it is: one hour on one date
 * (10 to 10 h), and dates that already differ, also once the hours stop crossing midnight.
 */
export function withOvernightHoursOnOneDateAsOneNight(period: Period): Period {
  const oneDate = period.startMonth === period.endMonth && period.startDay === period.endDay;
  if (!oneDate || period.startHour <= period.endHour) return period;
  const nextDay = monthDayOf(dayOfYear(period.startMonth, period.startDay) % DAYS_IN_YEAR + 1);
  return { ...period, endMonth: nextDay.month, endDay: nextDay.day };
}

export const PERIOD_PRESETS = ["winter_solstice", "summer_solstice", "heating_season", "whole_year"] as const;
export type PeriodPreset = (typeof PERIOD_PRESETS)[number];

const PRESET_DATES: Record<PeriodPreset, Pick<Period, "startMonth" | "startDay" | "endMonth" | "endDay">> = {
  winter_solstice: { startMonth: 12, startDay: 21, endMonth: 12, endDay: 21 },
  summer_solstice: { startMonth: 6, startDay: 21, endMonth: 6, endDay: 21 },
  heating_season: { startMonth: 10, startDay: 1, endMonth: 4, endDay: 30 },
  whole_year: { startMonth: 1, startDay: 1, endMonth: 12, endDay: 31 },
};

/** The period a preset gives: its dates, the hours of *current*; one night where those hours cross midnight on its one date. */
export function presetPeriod(preset: PeriodPreset, current: Period): Period {
  return withOvernightHoursOnOneDateAsOneNight({ ...current, ...PRESET_DATES[preset] });
}

/** Whether the dates of *current* are the ones the preset gives it: the preset shows as chosen. */
export function presetMatches(preset: PeriodPreset, current: Period): boolean {
  const given = presetPeriod(preset, current);
  return given.startMonth === current.startMonth && given.startDay === current.startDay
    && given.endMonth === current.endMonth && given.endDay === current.endDay;
}

/** The value a handle shows: a day of the year for a date handle, an hour for an hour handle. */
export function handleValueOf(period: Period, handle: PeriodHandle): number {
  switch (handle) {
    case "start_date": return dayOfYear(period.startMonth, period.startDay);
    case "end_date": return dayOfYear(period.endMonth, period.endDay);
    case "start_hour": return period.startHour;
    case "end_hour": return period.endHour;
  }
}

/** *period* with *handle* at *value* (a day of the year or an hour). The start may pass the end: the range then wraps. */
export function periodWithHandleAt(period: Period, handle: PeriodHandle, value: number): Period {
  switch (handle) {
    case "start_date": {
      const { month, day } = monthDayOf(value);
      return { ...period, startMonth: month, startDay: day };
    }
    case "end_date": {
      const { month, day } = monthDayOf(value);
      return { ...period, endMonth: month, endDay: day };
    }
    case "start_hour": return { ...period, startHour: holdTo(value, 0, LAST_HOUR) };
    case "end_hour": return { ...period, endHour: holdTo(value, 0, LAST_HOUR) };
  }
}

/** The day under the pointer, *fraction* of the way along the year strip: the day whose cell it is in. */
export function dayOfYearAt(fraction: number): number {
  return holdTo(Math.floor(fraction * DAYS_IN_YEAR) + 1, 1, DAYS_IN_YEAR);
}

/** The hour under the pointer, *fraction* of the way along the hour strip. */
export function hourAt(fraction: number): number {
  return holdTo(Math.floor(fraction * HOURS_IN_DAY), 0, LAST_HOUR);
}

/** Where a key moves a date handle (a day of the year): arrows one day, Page Up and Page Down a month, Home and End the year's ends. */
export function dateHandleValueAfterKey(day: number, key: string): number | null {
  const { month, day: dayOfMonth } = monthDayOf(day);
  const sameDayIn = (otherMonth: number) => dayOfYear(otherMonth, Math.min(dayOfMonth, daysInMonth(otherMonth)));
  switch (key) {
    case "ArrowRight": case "ArrowUp": return holdTo(day + 1, 1, DAYS_IN_YEAR);
    case "ArrowLeft": case "ArrowDown": return holdTo(day - 1, 1, DAYS_IN_YEAR);
    case "PageUp": return month === 12 ? DAYS_IN_YEAR : sameDayIn(month + 1);
    case "PageDown": return month === 1 ? 1 : sameDayIn(month - 1);
    case "Home": return 1;
    case "End": return DAYS_IN_YEAR;
    default: return null;
  }
}

/** Where a key moves an hour handle: arrows one hour, Page Up and Page Down six hours, Home and End 0 and 23 h. */
export function hourHandleValueAfterKey(hour: number, key: string): number | null {
  switch (key) {
    case "ArrowRight": case "ArrowUp": return holdTo(hour + 1, 0, LAST_HOUR);
    case "ArrowLeft": case "ArrowDown": return holdTo(hour - 1, 0, LAST_HOUR);
    case "PageUp": return holdTo(hour + HOURS_PER_PAGE, 0, LAST_HOUR);
    case "PageDown": return holdTo(hour - HOURS_PER_PAGE, 0, LAST_HOUR);
    case "Home": return 0;
    case "End": return LAST_HOUR;
    default: return null;
  }
}

/** *period* with the month of one end chosen; the day is held to that month's length, so no path gives 31 February. */
export function periodWithMonthChosen(period: Period, end: PeriodEnd, month: number): Period {
  return end === "start" ? { ...period, startMonth: month, startDay: Math.min(period.startDay, daysInMonth(month)) }
    : { ...period, endMonth: month, endDay: Math.min(period.endDay, daysInMonth(month)) };
}

/** *period* with the day of one end typed, held to the month's length. */
export function periodWithDayTyped(period: Period, end: PeriodEnd, day: number): Period {
  return end === "start" ? { ...period, startDay: holdTo(day, 1, daysInMonth(period.startMonth)) }
    : { ...period, endDay: holdTo(day, 1, daysInMonth(period.endMonth)) };
}

const FIELD_OF: Record<AnalysisPeriodField, keyof Period> = {
  start_month: "startMonth", start_day: "startDay", start_hour: "startHour", end_month: "endMonth", end_day: "endDay", end_hour: "endHour",
};

/** The six stored settings as a period, or null while one of them is not set. */
export function periodFromSettings(settings: Record<AnalysisPeriodField, number | null>): Period | null {
  const values = ANALYSIS_PERIOD_FIELDS.map((name) => settings[name]);
  if (values.some((value) => typeof value !== "number")) return null;
  return Object.fromEntries(ANALYSIS_PERIOD_FIELDS.map((name) => [FIELD_OF[name], settings[name]])) as unknown as Period;
}

/** The settings *next* changes against the stored ones (a setting not set yet is changed). */
export function changedPeriodSettings(settings: Record<AnalysisPeriodField, number | null>, next: Period): Partial<Record<AnalysisPeriodField, number>> {
  return Object.fromEntries(ANALYSIS_PERIOD_FIELDS.filter((name) => settings[name] !== next[FIELD_OF[name]]).map((name) => [name, next[FIELD_OF[name]]]));
}

/** A drawn piece of a range, as fractions of its strip. */
export interface RangeSegment {
  start: number;
  end: number;
}

/** One piece from *start* to *end*, or two where it wraps (the start after the end): from the start to the strip's end, and from its beginning to the end. */
function segments(start: number, end: number): RangeSegment[] {
  return start < end ? [{ start, end }] : [{ start, end: 1 }, { start: 0, end }];
}

/** The year strip's range: from the start of the start day to the end of the end day. */
export function dateRangeSegments(period: Period): RangeSegment[] {
  const startDay = dayOfYear(period.startMonth, period.startDay), endDay = dayOfYear(period.endMonth, period.endDay);
  if (startDay <= endDay) return [{ start: (startDay - 1) / DAYS_IN_YEAR, end: endDay / DAYS_IN_YEAR }];
  return segments((startDay - 1) / DAYS_IN_YEAR, endDay / DAYS_IN_YEAR);
}

/** The hour strip's range: the end hour is inclusive (10 to 14 h samples 10:00 through 14:00), so it runs to the end of that hour's mark. */
export function hourRangeSegments(period: Period): RangeSegment[] {
  if (period.startHour <= period.endHour) return [{ start: period.startHour / HOURS_IN_DAY, end: (period.endHour + 1) / HOURS_IN_DAY }];
  return segments(period.startHour / HOURS_IN_DAY, (period.endHour + 1) / HOURS_IN_DAY);
}

/** Where a handle is drawn, as a fraction of its strip: a start at the beginning of its day or hour, an end at the end of it. */
export function handlePositionOf(period: Period, handle: PeriodHandle): number {
  const value = handleValueOf(period, handle);
  switch (handle) {
    case "start_date": return (value - 1) / DAYS_IN_YEAR;
    case "end_date": return value / DAYS_IN_YEAR;
    case "start_hour": return value / HOURS_IN_DAY;
    case "end_hour": return (value + 1) / HOURS_IN_DAY;
  }
}
