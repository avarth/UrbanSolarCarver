import { expect, test } from "vitest";
import { minuteAfterKey, minuteAt } from "../simulate/SunPanel";
import { shadeHoursOf, shadeRequest } from "../simulate/use_sun_study";
import { singleBubbleShift } from "../settings_form/widgets/ScaleStrip";
import { shadeColour, sunAt, sunStudyObjects } from "./sun_study";
import { studyPaletteColour } from "./study_palettes";

const CHART = {
  key_days: [{ date: "06-21", runs: [[[0, -1, 0.001], [0, 0, 1]]] }],
  hour_lines: [{ hour: 12, runs: [[[0, -0.8, 0.6], [0, -0.6, 0.8], [0, -0.9, 0.4]]] }],
  day: { date: "12-21", runs: [[[1, 0, 0.01], [0, -0.7, 0.7]]] },
};

test("the sun path and the sun are placed on the hemisphere, each hour labelled at its highest point", () => {
  const objects = sunStudyObjects(CHART, [0, 0, 2], { centre: [10, 0, 0], radius: 50 });
  expect(objects.keyDays[0][1]).toEqual([10, 0, 50]);
  expect(objects.hourLines[0].labelAt).toEqual([10, -30, 40]);
  expect(objects.hourLines[0].label).toContain("12");
  expect(objects.day[0]).toHaveLength(2);
  expect(objects.sun).toEqual([10, 0, 50]);
  expect(sunStudyObjects(CHART, null, { centre: [0, 0, 0], radius: 1 }).sun).toBeNull();
});

test("the sun at a time is the nearest position within the tolerance; none further away", () => {
  const positions = [{ minute: 480, vector: [1, 0, 0] }, { minute: 485, vector: [0, 1, 0] }];
  expect(sunAt(positions, 484, 2.5)?.minute).toBe(485);
  expect(sunAt(positions, 470, 2.5)).toBeNull();
});

test("each position of the hours in shade stands for its step divided by the days sampled", () => {
  const positions = { positions: [{ date: "12-21", minute: 485, vector: [0, 0, 1], altitude: 90, azimuth: 0 }], days_sampled: 4, day_step: 7, step_minutes: 30 };
  expect(shadeHoursOf(positions, 8, "grey")).toEqual({ directions: [[0, 0, 1]], hoursEach: 0.125, maxHours: 8, palette: "grey" });
});

test("the hours in shade of a period: the middle of each step, from the start hour to the end of the end hour, over midnight too", () => {
  const day = { start_month: 12, start_day: 21, start_hour: 8, end_month: 12, end_day: 21, end_hour: 15 };
  expect(shadeRequest(day, "standard")).toEqual({ range: { from: "12-21", to: "12-21", start: 485, end: 955, step: 10, time_basis: "standard" }, hours: 8 });
  const winter = { ...day, end_month: 3, end_day: 21 };
  expect(shadeRequest(winter, "solar").range).toEqual({ from: "12-21", to: "03-21", start: 495, end: 945, step: 30, time_basis: "solar" });
  const night = { ...day, start_hour: 20, end_hour: 3 };
  expect(shadeRequest(night, "standard")).toEqual({ range: { from: "12-21", to: "12-21", start: 1205, end: 235, step: 10, time_basis: "standard" }, hours: 8 });
});

test("the shade colours run from light (no shade) to dark (the whole range), in viridis or grey", () => {
  expect(shadeColour("viridis", 0)).toBe(studyPaletteColour("viridis", 1));
  expect(shadeColour("viridis", 1)).toBe(studyPaletteColour("viridis", 0));
  expect([shadeColour("grey", 0), shadeColour("grey", 1)]).toEqual(["#f2f2f2", "#262626"]);
});

test("the time strip moves in 5 minute steps, an hour a page, and the single bubble stays over the strip", () => {
  expect(minuteAt(0.5)).toBe(720);
  expect(minuteAt(1)).toBe(1435);
  expect([minuteAfterKey(720, "ArrowRight"), minuteAfterKey(720, "PageDown"), minuteAfterKey(10, "Home"), minuteAfterKey(720, "x")]).toEqual([725, 660, 0, null]);
  expect(singleBubbleShift(5, 40, 300)).toEqual([15, 0]);
  expect(singleBubbleShift(150, 40, 300)).toEqual([0, 0]);
});
