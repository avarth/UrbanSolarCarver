import { expect, test } from "vitest";
import { gridLineCoordinates, groundGridSpacing } from "./ground_grid";

test("ground grid is 10 m with 50 and 100 m lines, 1 m for small models", () => {
  expect(groundGridSpacing(80)).toEqual({minorMetres: 10, majorMetres: [50, 100], extentMetres: 1000});
  expect(groundGridSpacing(12)).toEqual({minorMetres: 1, majorMetres: [10, 50], extentMetres: 1000});
});

test("grid lines fall on multiples of the spacing, sorted into minor and the two major strengths", () => {
  const lines = gridLineCoordinates(groundGridSpacing(80), 5, 120);    // model centre at 5 m, lines up to 120 m from it
  expect(lines.strongest).toEqual([-100, 0, 100]);
  expect(lines.major).toEqual([-50, 50]);
  expect(lines.minor).toContain(10);
  expect(lines.minor).not.toContain(50);
  expect(Math.min(...lines.minor)).toBe(-110);
  expect(Math.max(...lines.minor)).toBe(120);
});
