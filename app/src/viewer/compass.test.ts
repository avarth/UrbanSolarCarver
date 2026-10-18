import { expect, test } from "vitest";
import { axisScreenDirections, northDirection, northNeedleScreenAngle } from "./compass";

test("north needle turns against the camera", () => {
  expect(northNeedleScreenAngle(0, 20)).toBe(20); expect(northNeedleScreenAngle(30, 20)).toBe(350);
});

test("north is measured clockwise from +Y", () => {
  const [x, y] = northDirection(90);
  expect(x).toBeCloseTo(1); expect(y).toBeCloseTo(0);
});

test("axes on screen: X right and Y up in the top view, Z up in a level view", () => {
  const top = axisScreenDirections(0, 90);
  expect(top.x[0]).toBeCloseTo(1); expect(top.x[1]).toBeCloseTo(0);
  expect(top.y[0]).toBeCloseTo(0); expect(top.y[1]).toBeCloseTo(1);
  expect(top.z[0]).toBeCloseTo(0); expect(top.z[1]).toBeCloseTo(0);
  const level = axisScreenDirections(90, 0);    // looking along +X
  expect(level.z[1]).toBeCloseTo(1);
  expect(level.x[0]).toBeCloseTo(0); expect(level.x[1]).toBeCloseTo(0);
  expect(level.y[0]).toBeCloseTo(-1);           // +Y is to the left when looking along +X with Z up
});
