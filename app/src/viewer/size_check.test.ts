import { expect, test } from "vitest";
import { sizeWarning } from "./size_check";

test("size warning for kilometres and millimetres only", () => {
  expect(sizeWarning([[0, 0, 0], [12000, 10, 10]])).toMatch("10\u00a0km");
  expect(sizeWarning([[0, 0, 0], [0.5, 0.2, 0.1]])).toMatch("1\u00a0m");
  expect(sizeWarning([[0, 0, 0], [80, 60, 33]])).toBeNull();
});

test("the size warnings are the texts of the technical spec", () => {
  expect(sizeWarning([[0, 0, 0], [12000, 10, 10]])).toBe("This model is more than 10\u00a0km across. Is it in meters?");
  expect(sizeWarning([[0, 0, 0], [0.5, 0.2, 0.1]])).toBe("This model is less than 1\u00a0m across. Is it in meters?");
});

test("the longest side decides, whichever axis it lies on", () => {
  expect(sizeWarning([[0, 0, 0], [5, 5, 10001]])).not.toBeNull();
  expect(sizeWarning([[0, 0, 0], [0.2, 0.9, 0.3]])).not.toBeNull();
  expect(sizeWarning([[0, 0, 0], [10000, 1, 1]])).toBeNull();
  expect(sizeWarning([[0, 0, 0], [1, 0.1, 0.1]])).toBeNull();
});
