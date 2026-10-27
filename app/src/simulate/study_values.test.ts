import { expect, test } from "vitest";
import { changeOf, changeTolerance, highestOf, percentile, statisticsOf } from "./study_values";

test("statisticsOf gives mean, 10th percentile and share at the target", () => {
  const values = Float32Array.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  const statistics = statisticsOf(values, 7.5);
  expect(statistics.mean).toBeCloseTo(5);
  expect(statistics.lowestTenth).toBeCloseTo(1);            // the 10th percentile, interpolated as numpy does
  expect(statistics.shareAtTarget).toBeCloseTo(3 / 11);     // 8, 9 and 10 are at or above the target
  expect(statisticsOf(values, 10).shareAtTarget).toBeCloseTo(1 / 11);      // at the target counts
  expect(statisticsOf(values, null).shareAtTarget).toBeNull();
  // The input is not sorted in place.
  const unsorted = Float32Array.from([3, 1, 2]);
  statisticsOf(unsorted, null);
  expect(Array.from(unsorted)).toEqual([3, 1, 2]);
});

test("the 10th percentile interpolates between the two nearest points", () => {
  expect(percentile(Float32Array.from([0, 10]), 0.1)).toBeCloseTo(1);
  expect(percentile(Float32Array.from([5]), 0.1)).toBe(5);
  expect(Number.isNaN(percentile(new Float32Array(0), 0.1))).toBe(true);
  expect(Number.isNaN(statisticsOf(new Float32Array(0), 1).mean)).toBe(true);
});

test("changeOf is the value less the baseline, point by point", () => {
  expect(Array.from(changeOf(Float32Array.from([3, 1, 4]), Float32Array.from([1, 1, 5])))).toEqual([2, 0, -1]);
});

test("the change tolerance is a thousandth of the highest value of the open column or the maximum volume", () => {
  expect(changeTolerance(Float32Array.from([2, 8, 4]), Float32Array.from([1, 5, 3]))).toBeCloseTo(0.008);
  expect(changeTolerance(Float32Array.from([2]), Float32Array.from([9]))).toBeCloseTo(0.009);
  expect(changeTolerance(undefined, Float32Array.from([0]))).toBeGreaterThan(0);
  expect(highestOf(Float32Array.from([1, 7, 3]))).toBe(7);
  expect(highestOf(new Float32Array(0))).toBe(0);
});
