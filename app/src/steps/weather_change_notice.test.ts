import { expect, test } from "vitest";
import type { ColdPeriodState, Period } from "../settings_form/analysis_period";
import { weatherChangeSuggestion, type WeatherFileChange, type WeatherChangeSituation } from "./weather_change_notice";

const period = (startMonth: number, startDay: number, startHour: number, endMonth: number, endDay: number, endHour: number): Period =>
  ({ startMonth, startDay, startHour, endMonth, endDay, endHour });
const WINTER_DAY = period(12, 21, 10, 12, 21, 14);
const COLD_SEASON = period(9, 30, 0, 5, 15, 23);
const BRISBANE_COLD_DATES = { startMonth: 5, startDay: 3, endMonth: 9, endDay: 20 };
const BRISBANE_COLD: ColdPeriodState = { kind: "found", dates: BRISBANE_COLD_DATES, baseTemperature: 13 };

const toBrisbane = (periodBefore: Period | null = WINTER_DAY): WeatherFileChange =>
  ({ weatherFileRevision: 1, location: "Brisbane, AUS", previousHemisphere: "northern", newHemisphere: "southern", periodBefore });

function situation(overrides: Partial<WeatherChangeSituation> = {}): WeatherChangeSituation {
  return { mode: "time-based", modeReadsPeriod: true, period: WINTER_DAY, coldPeriod: null, answeredWeatherFileRevision: null, ...overrides };
}

test("no weather change in this session: no suggestion", () => {
  expect(weatherChangeSuggestion(null, situation())).toBeNull();
});

test("a period-reading mode, the other hemisphere: the period six months on", () => {
  expect(weatherChangeSuggestion(toBrisbane(), situation())).toEqual(
    { kind: "six_months", location: "Brisbane, AUS", hemisphere: "southern", suggested: period(6, 21, 10, 6, 21, 14) });
  expect(weatherChangeSuggestion(toBrisbane(), situation({ mode: "irradiance" }))?.kind).toBe("six_months");
});

test("the same hemisphere, a file without a latitude, a mode that reads no period, or a period not set: no suggestion", () => {
  expect(weatherChangeSuggestion({ ...toBrisbane(), previousHemisphere: "southern" }, situation())).toBeNull();
  expect(weatherChangeSuggestion({ ...toBrisbane(), newHemisphere: null }, situation())).toBeNull();
  expect(weatherChangeSuggestion(toBrisbane(), situation({ mode: "daylight", modeReadsPeriod: false, period: null }))).toBeNull();
  expect(weatherChangeSuggestion(toBrisbane(null), situation({ period: null }))).toBeNull();
});

test("once the period is not the one the weather file found, by the button or by hand, the suggestion is gone", () => {
  expect(weatherChangeSuggestion(toBrisbane(), situation({ period: period(6, 21, 10, 6, 21, 14) }))).toBeNull();
  expect(weatherChangeSuggestion(toBrisbane(), situation({ period: period(12, 21, 9, 12, 21, 14) }))).toBeNull();
});

test("Solar usefulness: the cold period of the new file, once its answer is in, with the hours kept", () => {
  const benefit = { mode: "benefit", period: COLD_SEASON, coldPeriod: BRISBANE_COLD };
  expect(weatherChangeSuggestion(toBrisbane(COLD_SEASON), situation({ ...benefit, answeredWeatherFileRevision: 1 }))).toEqual({
    kind: "cold_period", location: "Brisbane, AUS", coldDates: BRISBANE_COLD_DATES,
    current: COLD_SEASON, suggested: period(5, 3, 0, 9, 20, 23),
  });
  // The answer of the earlier file, or none yet: wait.
  expect(weatherChangeSuggestion(toBrisbane(COLD_SEASON), situation({ ...benefit, answeredWeatherFileRevision: 0 }))).toBeNull();
  expect(weatherChangeSuggestion(toBrisbane(COLD_SEASON), situation({ ...benefit, coldPeriod: { kind: "finding" } }))).toBeNull();
});

test("Solar usefulness: no cold period, or one the analysis period already has: no suggestion, whatever the hemisphere", () => {
  const benefit = { mode: "benefit", period: COLD_SEASON, answeredWeatherFileRevision: 1 };
  expect(weatherChangeSuggestion(toBrisbane(COLD_SEASON), situation({ ...benefit, coldPeriod: { kind: "none", baseTemperature: 13 } }))).toBeNull();
  const sameDates: ColdPeriodState = { kind: "found", dates: { startMonth: 9, startDay: 30, endMonth: 5, endDay: 15 }, baseTemperature: 13 };
  expect(weatherChangeSuggestion(toBrisbane(COLD_SEASON), situation({ ...benefit, coldPeriod: sameDates }))).toBeNull();
});
