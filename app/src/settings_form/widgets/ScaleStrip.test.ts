import { expect, test } from "vitest";
import { valueBubbleShifts } from "./ScaleStrip";

// Two bubbles 40 px wide on a strip 300 px wide, 4 px apart at the least.
const bubbles = (startCentre: number, endCentre: number, stripWidth = 300) =>
  valueBubbleShifts({ centres: [startCentre, endCentre], widths: [40, 40], stripWidth, gap: 4 });

test("bubbles far apart stay centred over their handles", () => {
  expect(bubbles(50, 250)).toEqual([0, 0]);
});

test("bubbles that would overlap move apart by the same amount, to the gap between them", () => {
  // Centred they would span 80 to 120 and 90 to 130: 34 px too close with the gap.
  expect(bubbles(100, 110)).toEqual([-17, 17]);
});

test("handles on one spot: the start's bubble goes to the left, the end's to the right", () => {
  expect(bubbles(150, 150)).toEqual([-22, 22]);
});

test("a start after the end (a wrapped period): the end's bubble is the left one", () => {
  expect(bubbles(110, 100)).toEqual([17, -17]);
});

test("bubbles are kept over the strip, pushed apart from its end", () => {
  expect(bubbles(5, 250)).toEqual([15, 0]);
  expect(bubbles(0, 0)).toEqual([20, 64]);
  expect(bubbles(300, 300)).toEqual([-64, -20]);
});

test("a strip not measured yet (no layout) leaves the bubbles centred", () => {
  expect(bubbles(0, 0, 0)).toEqual([0, 0]);
});
