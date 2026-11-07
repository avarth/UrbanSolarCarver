import { expect, test } from "vitest";
import { sunAt, sunStudyObjects } from "./sun_study";

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
