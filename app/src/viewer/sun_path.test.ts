import { expect, test } from "vitest";
import { sunPathLegend, sunPathObjects } from "./sun_path";

test("sun path objects: two lines per day and one sun per marker", () => {
  const day = {date: "12-21", day_path: [[1, 0, 0.1], [0, -1, 0.4], [-1, 0, 0.1]], period_path: [[0.3, -1, 0.4], [-0.3, -1, 0.4]],
               markers: [{hour: 10, vector: [0.3, -1, 0.4]}, {hour: 12, vector: [0, -1, 0.45]}]};
  const objects = sunPathObjects({days: [day]}, {centre: [0, 0, 0], radius: 54});
  expect(objects.lines).toHaveLength(2); expect(objects.markers.map(m => m.label)).toEqual(["10 h", "12 h"]);
});

test("points lie on the hemisphere around its centre", () => {
  const day = {date: "06-21", day_path: [[0, 1, 0], [0, 0, 1]], period_path: [], markers: [{hour: 12, vector: [0, 0, 1]}]};
  const objects = sunPathObjects({days: [day]}, {centre: [10, 20, 2], radius: 50});
  const dayLine = objects.lines.find(line => line.kind === "day_path")!;
  expect(dayLine.runs).toEqual([[[10, 70, 2], [10, 20, 52]]]);
  expect(objects.markers[0].position).toEqual([10, 20, 52]);
});

function sunAtHour(hour: number): number[] {
  const angle = ((hour - 12) / 24) * 2 * Math.PI;      // a sun that turns 15 degrees an hour around a tilted axis
  return [Math.sin(angle) * 0.9, -Math.cos(angle) * 0.9, 0.4359];
}

test("a period over midnight is drawn as two runs, so its early and its evening hours are not joined", () => {
  const earlyHours = [0, 0.25, 0.5, 0.75, 1].map(hour => sunAtHour(hour));       // 00:00 to 01:00
  const eveningHours = [22, 22.25, 22.5].map(hour => sunAtHour(hour));          // 22:00 to 22:30
  const day = {date: "06-21", day_path: [], period_path: [...earlyHours, ...eveningHours], markers: []};
  const periodLine = sunPathObjects({days: [day]}, {centre: [0, 0, 0], radius: 1}).lines.find(line => line.kind === "period_path")!;
  expect(periodLine.runs.map(run => run.length)).toEqual([5, 3]);
});

test("sun path legend names the days and the hours with a sun", () => {
  const day = (date: string) => ({date, day_path: [], period_path: [], markers: [10, 12, 14].map(hour => ({hour, vector: [0, 0, 1]}))});
  expect(sunPathLegend({days: [day("12-21")]})).toBe("Sun path, 21 Dec; sun at 10, 12 and 14 h");
  expect(sunPathLegend({days: [day("06-01"), day("08-31")]})).toBe("Sun path, 1 Jun and 31 Aug; sun at 10, 12 and 14 h");
});
