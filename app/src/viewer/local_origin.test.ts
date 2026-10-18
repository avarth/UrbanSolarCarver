import { expect, test } from "vitest";
import { localOrigin, toLocal } from "./local_origin";

test("georeferenced coordinates keep millimetre precision after the shift", () => {
  const origin = localOrigin([[500000.25, 4200000.5, 10], [500100.25, 4200050.5, 40]]);
  const local = Float32Array.from(toLocal([500012.345, 4200007.891, 12.5], origin));
  expect(local[0]).toBeCloseTo(12.095, 3); expect(local[1]).toBeCloseTo(7.391, 3);
});

test("the local origin is the minimum corner", () => {
  expect(localOrigin([[1, 2, 3], [4, 5, 6]])).toEqual([1, 2, 3]);
});
