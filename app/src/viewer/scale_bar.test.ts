import { expect, test } from "vitest";
import { scaleBarLabel, scaleBarLength } from "./scale_bar";

test("scale bar picks 1, 2, 5 steps at least 100 px long", () => {
  expect(scaleBarLength(0.1)).toEqual({metres: 10, pixels: 100});
  expect(scaleBarLength(0.13)).toEqual({metres: 20, pixels: 20 / 0.13});
});

test("the scale bar stays between 100 and 250 px at any zoom", () => {
  for (const metresPerPixel of [0.0007, 0.004, 0.021, 0.3, 0.49, 0.51, 1.9, 7.3, 42]) {
    const { pixels } = scaleBarLength(metresPerPixel);
    expect(pixels).toBeGreaterThanOrEqual(100 - 1e-9);
    expect(pixels).toBeLessThanOrEqual(250 + 1e-9);
  }
  expect(scaleBarLength(0.004).metres).toBe(0.5);
});

test("the scale bar label reads 0 to the length", () => {
  expect(scaleBarLabel(20)).toBe("0 to 20 m");
  expect(scaleBarLabel(0.5)).toBe("0 to 0.5 m");
  expect(scaleBarLabel(1000)).toBe("0 to 1 000 m");
});
