import { expect, test } from "vitest";
import { facingGroups, highestOf, noBuildTolerance, percentile, statisticsOf, valuesAt } from "./study_values";

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

test("the no-build tolerance is a thousandth of the highest value of the open column", () => {
  expect(noBuildTolerance(Float32Array.from([2, 8, 4]))).toBeCloseTo(0.008);
  expect(noBuildTolerance(undefined)).toBeGreaterThan(0);
  expect(highestOf(Float32Array.from([1, 7, 3]))).toBe(7);
  expect(highestOf(new Float32Array(0))).toBe(0);
});

/** A unit patch whose corners wind around *normal* (x, y, z), at the origin. */
function patchFacing(normal: [number, number, number]): number[] {
  const [nx, ny, nz] = normal;
  const reference: [number, number, number] = Math.abs(nz) > 0.9 ? [1, 0, 0] : [0, 0, 1];
  const first = [reference[1] * nz - reference[2] * ny, reference[2] * nx - reference[0] * nz, reference[0] * ny - reference[1] * nx];
  const second = [ny * first[2] - nz * first[1], nz * first[0] - nx * first[2], nx * first[1] - ny * first[0]];
  return [[0, 0], [1, 0], [1, 1], [0, 1]].flatMap(([a, b]) => [0, 1, 2].map((axis) => a * first[axis] + b * second[axis]));
}

test("facingGroups puts roofs apart and each facade in the sector of the compass point it faces, turned by north", () => {
  // A point not on the geometry first, then a roof, a facade facing +y (north with north at 0), +x, -y, -x, and a slope of 30 degrees.
  const normals: [number, number, number][] = [[0, 0, 1], [0, 0, 1], [0, 1, 0], [1, 0, 0], [0, -1, 0], [-1, 0, 0], [0, Math.sin(Math.PI / 3), 0.5]];
  const quads = Float32Array.from(normals.flatMap(patchFacing));
  const groups = facingGroups(quads, 1, normals.length, 0);
  expect(Object.fromEntries(Object.entries(groups).map(([group, indices]) => [group, Array.from(indices)])))
    .toEqual({ roof: [1], N: [2, 6], E: [3], S: [4], W: [5] });
  // North 90 degrees clockwise from +y: +x is now north, +y west.
  const turned = facingGroups(quads, 1, normals.length, 90);
  expect(Array.from(turned.N)).toEqual([3]);
  expect(Array.from(turned.W)).toEqual([2, 6]);
  expect(Array.from(valuesAt(Float32Array.from([5, 6, 7, 8]), Uint32Array.from([3, 1])))).toEqual([8, 6]);
});
