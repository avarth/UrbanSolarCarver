import { afterEach, expect, test } from "vitest";
import { cividis, keptScoreRange, storeyColour, sunRamp } from "./colour_scales";

afterEach(() => {
  document.documentElement.removeAttribute("style");
});

test("cividis endpoints", () => { expect(cividis(0)).toBe("#00224e"); expect(cividis(1)).toBe("#fee838"); });

test("cividis is matplotlib's at the middle and clamps outside 0 to 1", () => {
  expect(cividis(0.5)).toBe("#7d7c78");
  expect(cividis(-1)).toBe("#00224e");
  expect(cividis(2)).toBe("#fee838");
});

test("kept voxels are coloured over 0 to the cutoff", () => { expect(keptScoreRange(1.5)).toEqual([0, 1.5]); });

test("storeys run from light to slate", () => {
  expect(storeyColour(0, 7)).toBe("#dfe6ea");
  expect(storeyColour(6, 7)).toBe("#2f5d7c");
  expect(storeyColour(0, 1)).toBe("#dfe6ea");
});

test("the sun ramp runs from the viewport background to the sun colour", () => {
  document.documentElement.style.setProperty("--colour-viewport-light", "#e3e8e7");
  document.documentElement.style.setProperty("--colour-viewport-dark", "#22303a");
  document.documentElement.style.setProperty("--colour-sun", "#f2b632");
  expect(sunRamp(0, "light")).toBe("#e3e8e7");
  expect(sunRamp(0, "dark")).toBe("#22303a");
  expect(sunRamp(1, "dark")).toBe("#f2b632");
});
