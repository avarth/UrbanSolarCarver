import { expect, test } from "vitest";
import {
  changedPeriodSettings, dateHandleValueAfterKey, dayOfYear, dayOfYearAt, daysInMonth, hourAt, hourHandleValueAfterKey, monthDayOf,
  periodFromSettings, periodInWords, periodWithDayTyped, periodWithHandleAt, periodWithMonthChosen, presetPeriod, presetMatches,
  runsEveryNightOfTheYear, withOvernightHoursOnOneDateAsOneNight, dateRangeSegments, hourRangeSegments, type Period,
} from "./analysis_period";

const period = (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number): Period =>
  ({ startMonth, startDay, startHour, endMonth, endDay, endHour });

test("day of the year and back, in a year that is not a leap year", () => {
  expect(dayOfYear(1, 1)).toBe(1);
  expect(dayOfYear(3, 1)).toBe(60);
  expect(dayOfYear(12, 21)).toBe(355);
  expect(dayOfYear(12, 31)).toBe(365);
  expect(monthDayOf(1)).toEqual({ month: 1, day: 1 });
  expect(monthDayOf(59)).toEqual({ month: 2, day: 28 });
  expect(monthDayOf(60)).toEqual({ month: 3, day: 1 });
  expect(monthDayOf(365)).toEqual({ month: 12, day: 31 });
  for (let day = 1; day <= 365; day += 1) expect(dayOfYear(monthDayOf(day).month, monthDayOf(day).day)).toBe(day);
  expect(daysInMonth(2)).toBe(28);
});

test("the period in words: one date, a range, across the new year, across midnight", () => {
  expect(periodInWords(period(12, 21, 10, 12, 21, 14))).toBe("21 Dec, 10 to 14\u00a0h");
  expect(periodInWords(period(10, 1, 0, 4, 30, 23))).toBe("1 Oct to 30 Apr, 0 to 23\u00a0h");
  expect(periodInWords(period(12, 21, 22, 12, 22, 2))).toBe("21 to 22 Dec, 22 to 2\u00a0h");
  expect(periodInWords(period(12, 31, 22, 1, 1, 2))).toBe("31 Dec to 1 Jan, 22 to 2\u00a0h");
  // Across the new year within one month: both months written, never "22 to 21 Dec".
  expect(periodInWords(period(12, 22, 10, 12, 21, 14))).toBe("22 Dec to 21 Dec, 10 to 14\u00a0h");
});

test("one date with hours across midnight, stored so: the engine runs every night of the year, and the words and the year strip say so", () => {
  const storedOvernight = period(12, 21, 22, 12, 21, 2);
  expect(runsEveryNightOfTheYear(storedOvernight)).toBe(true);
  expect(periodInWords(storedOvernight)).toBe("Every night, 22 to 2\u00a0h");
  expect(dateRangeSegments(storedOvernight)).toEqual([{ start: 0, end: 1 }]);
  for (const otherPeriod of [period(12, 21, 22, 12, 22, 2), period(12, 21, 10, 12, 21, 10), period(12, 21, 10, 12, 21, 14)]) {
    expect(runsEveryNightOfTheYear(otherPeriod)).toBe(false);
  }
});

test("hours across midnight on one date: the end date becomes the next day, 31 December gives 1 January", () => {
  expect(withOvernightHoursOnOneDateAsOneNight(period(12, 21, 22, 12, 21, 2))).toEqual(period(12, 21, 22, 12, 22, 2));
  expect(withOvernightHoursOnOneDateAsOneNight(period(12, 31, 22, 12, 31, 2))).toEqual(period(12, 31, 22, 1, 1, 2));
  expect(withOvernightHoursOnOneDateAsOneNight(period(2, 28, 23, 2, 28, 0))).toEqual(period(2, 28, 23, 3, 1, 0));
  // Left as they are: one hour on one date, hours not across midnight, two dates, and dates across the new year.
  for (const unchanged of [period(12, 21, 10, 12, 21, 10), period(12, 21, 10, 12, 21, 14), period(12, 21, 22, 12, 22, 2), period(10, 1, 22, 4, 30, 2)]) {
    expect(withOvernightHoursOnOneDateAsOneNight(unchanged)).toEqual(unchanged);
  }
});

test("the presets set the dates and keep the hours", () => {
  const current = period(3, 5, 9, 3, 9, 17);
  expect(presetPeriod("winter_solstice", current)).toEqual(period(12, 21, 9, 12, 21, 17));
  expect(presetPeriod("summer_solstice", current)).toEqual(period(6, 21, 9, 6, 21, 17));
  expect(presetPeriod("heating_season", current)).toEqual(period(10, 1, 9, 4, 30, 17));
  expect(presetPeriod("whole_year", current)).toEqual(period(1, 1, 9, 12, 31, 17));
});

test("a preset of one date with hours across midnight gives one night, and still shows as chosen", () => {
  const acrossMidnight = period(3, 5, 22, 3, 9, 2);
  expect(presetPeriod("winter_solstice", acrossMidnight)).toEqual(period(12, 21, 22, 12, 22, 2));
  expect(presetMatches("winter_solstice", period(12, 21, 22, 12, 22, 2))).toBe(true);
  expect(presetMatches("winter_solstice", period(12, 21, 10, 12, 21, 14))).toBe(true);
  expect(presetMatches("winter_solstice", period(12, 21, 10, 12, 22, 14))).toBe(false);
  expect(presetMatches("heating_season", period(10, 1, 0, 4, 30, 23))).toBe(true);
});

test("a handle moved to a day or an hour; the start may pass the end, across the new year or midnight", () => {
  const winterDay = period(12, 21, 10, 12, 21, 14);
  expect(periodWithHandleAt(winterDay, "start_date", dayOfYear(10, 1))).toEqual(period(10, 1, 10, 12, 21, 14));
  expect(periodWithHandleAt(period(10, 1, 10, 12, 21, 14), "end_date", dayOfYear(4, 30))).toEqual(period(10, 1, 10, 4, 30, 14));
  expect(periodWithHandleAt(winterDay, "end_hour", 2)).toEqual(period(12, 21, 10, 12, 21, 2));
  expect(periodWithHandleAt(winterDay, "start_hour", 22)).toEqual(period(12, 21, 22, 12, 21, 14));
});

test("the day and the hour under the pointer: the cell it is in, held to the strip", () => {
  expect(dayOfYearAt(0)).toBe(1);
  expect(dayOfYearAt(0.5 / 365)).toBe(1);
  expect(dayOfYearAt(354.5 / 365)).toBe(355);
  expect(dayOfYearAt(1)).toBe(365);
  expect(dayOfYearAt(-0.2)).toBe(1);
  expect(dayOfYearAt(1.3)).toBe(365);
  expect(hourAt(0)).toBe(0);
  expect(hourAt(10.5 / 24)).toBe(10);
  expect(hourAt(1)).toBe(23);
});

test("keys on a date handle: arrows one day, Page Up and Page Down a month, Home and End the ends of the year", () => {
  const day = dayOfYear(12, 21);
  expect(dateHandleValueAfterKey(day, "ArrowRight")).toBe(day + 1);
  expect(dateHandleValueAfterKey(day, "ArrowUp")).toBe(day + 1);
  expect(dateHandleValueAfterKey(day, "ArrowLeft")).toBe(day - 1);
  expect(dateHandleValueAfterKey(day, "ArrowDown")).toBe(day - 1);
  expect(dateHandleValueAfterKey(dayOfYear(1, 31), "PageUp")).toBe(dayOfYear(2, 28));     // never 31 February
  expect(dateHandleValueAfterKey(dayOfYear(3, 31), "PageDown")).toBe(dayOfYear(2, 28));
  expect(dateHandleValueAfterKey(dayOfYear(12, 21), "PageUp")).toBe(365);
  expect(dateHandleValueAfterKey(dayOfYear(1, 21), "PageDown")).toBe(1);
  expect(dateHandleValueAfterKey(365, "ArrowRight")).toBe(365);
  expect(dateHandleValueAfterKey(1, "ArrowLeft")).toBe(1);
  expect(dateHandleValueAfterKey(day, "Home")).toBe(1);
  expect(dateHandleValueAfterKey(day, "End")).toBe(365);
  expect(dateHandleValueAfterKey(day, "a")).toBeNull();
});

test("keys on an hour handle: arrows one hour, Page Up and Page Down six hours, Home and End 0 and 23 h", () => {
  expect(hourHandleValueAfterKey(10, "ArrowRight")).toBe(11);
  expect(hourHandleValueAfterKey(10, "ArrowDown")).toBe(9);
  expect(hourHandleValueAfterKey(10, "PageUp")).toBe(16);
  expect(hourHandleValueAfterKey(20, "PageUp")).toBe(23);
  expect(hourHandleValueAfterKey(3, "PageDown")).toBe(0);
  expect(hourHandleValueAfterKey(23, "ArrowUp")).toBe(23);
  expect(hourHandleValueAfterKey(10, "Home")).toBe(0);
  expect(hourHandleValueAfterKey(10, "End")).toBe(23);
  expect(hourHandleValueAfterKey(10, "Enter")).toBeNull();
});

test("31 February cannot be produced: a month change holds the day to the month's length", () => {
  expect(periodWithMonthChosen(period(1, 31, 10, 3, 31, 14), "start", 2)).toEqual(period(2, 28, 10, 3, 31, 14));
  expect(periodWithMonthChosen(period(1, 1, 10, 3, 31, 14), "end", 4)).toEqual(period(1, 1, 10, 4, 30, 14));
  expect(periodWithDayTyped(period(2, 1, 10, 3, 1, 14), "start", 28)).toEqual(period(2, 28, 10, 3, 1, 14));
  expect(periodWithDayTyped(period(2, 1, 10, 3, 1, 14), "start", 31)).toEqual(period(2, 28, 10, 3, 1, 14));
});

test("the stored settings as a period, and the settings a new period changes", () => {
  const stored = { start_month: 12, start_day: 21, start_hour: 10, end_month: 12, end_day: 21, end_hour: 14 };
  expect(periodFromSettings(stored)).toEqual(period(12, 21, 10, 12, 21, 14));
  expect(periodFromSettings({ ...stored, end_hour: null })).toBeNull();
  expect(changedPeriodSettings(stored, period(12, 21, 22, 12, 22, 2))).toEqual({ start_hour: 22, end_day: 22, end_hour: 2 });
  expect(changedPeriodSettings(stored, period(12, 21, 10, 12, 21, 14))).toEqual({});
  expect(changedPeriodSettings({ ...stored, end_hour: null }, period(12, 21, 10, 12, 21, 14))).toEqual({ end_hour: 14 });
});

test("the drawn ranges: one piece, or two wrapped pieces across the new year or midnight; the end hour is drawn to the end of its mark", () => {
  expect(dateRangeSegments(period(12, 21, 10, 12, 21, 14))).toEqual([{ start: 354 / 365, end: 355 / 365 }]);
  expect(dateRangeSegments(period(10, 1, 10, 4, 30, 14))).toEqual([{ start: 273 / 365, end: 1 }, { start: 0, end: 120 / 365 }]);
  expect(hourRangeSegments(period(12, 21, 10, 12, 21, 14))).toEqual([{ start: 10 / 24, end: 15 / 24 }]);
  expect(hourRangeSegments(period(12, 21, 22, 12, 22, 2))).toEqual([{ start: 22 / 24, end: 1 }, { start: 0, end: 3 / 24 }]);
  expect(hourRangeSegments(period(1, 1, 0, 12, 31, 23))).toEqual([{ start: 0, end: 1 }]);
});
