import { expect, test } from "vitest";
import { histogramBins, logAxisDecades, logAxisHeight, stackedBarHeights } from "./score_histogram";

test("histogram bins split kept and carved and count every voxel", () => {
  const bins = histogramBins(Float32Array.from([0, 0, 1, 5, 9]), Uint8Array.from([1, 1, 1, 0, 0]), 3);
  expect(bins.reduce((n, b) => n + b.keptCount + b.carvedCount, 0)).toBe(5);
  expect(bins[0]).toMatchObject({ keptCount: 3, carvedCount: 0 });
  expect(bins[2]).toMatchObject({ keptCount: 0, carvedCount: 1 });
  expect(bins.map((bin) => [bin.lower, bin.upper])).toEqual([[0, 3], [3, 6], [6, 9]]);
});

test("scores that are all the same fall in one bin", () => {
  const bins = histogramBins(Float32Array.from([2, 2, 2]), Uint8Array.from([1, 0, 1]), 4);
  expect(bins).toHaveLength(1);
  expect(bins[0]).toMatchObject({ lower: 2, upper: 2, keptCount: 2, carvedCount: 1 });
  expect(histogramBins(new Float32Array(0), new Uint8Array(0), 4)).toEqual([]);
});

test("on the log scale the carved part sits on top of the kept part", () => {
  // The axis runs from 0.5 (log10 = -0.301) to 10 000 (4): 4.301 decades. Kept 100 reaches 2.301 of them, kept + carved 1000 one more.
  const h = stackedBarHeights(100, 900, "log", 100, 4);
  expect(h.kept).toBeCloseTo((2.30103 / 4.30103) * 100);
  expect(h.carved).toBeCloseTo((1 / 4.30103) * 100);
  expect(stackedBarHeights(0, 0, "log", 100, 4)).toEqual({ kept: 0, carved: 0 });
});

test("one voxel has a height on the log axis, below the first tick at 1", () => {
  const one = stackedBarHeights(1, 0, "log", 100, 4);
  expect(one.kept).toBeGreaterThan(0);
  expect(one.kept).toBeCloseTo(logAxisHeight(1, 4, 100));
  expect(stackedBarHeights(0, 1, "log", 100, 4).carved).toBeCloseTo(one.kept);
  expect(logAxisHeight(10_000, 4, 100)).toBeCloseTo(100);
});

test("on the linear scale each part is its count over the top of the axis", () => {
  const h = stackedBarHeights(250, 750, "linear", 100, 2000);
  expect(h.kept).toBeCloseTo(12.5);
  expect(h.carved).toBeCloseTo(37.5);
});

test("the log axis reaches the next even power of ten above the largest bar", () => {
  expect(logAxisDecades(880 + 92)).toBe(4);
  expect(logAxisDecades(5)).toBe(2);
  expect(logAxisDecades(0)).toBe(2);
  expect(logAxisDecades(150_000)).toBe(6);
});
