import { expect, test } from "vitest";
import { carveAmountAt, cutoffForCarveAmount, cutoffStep, keptShareAt, rankScorePoints, roundedToStep } from "./cutoff_preview";

// Five points: compared scores 1 to 5 (in another order), each holding its own score; one point has no compared score.
const COMPARED = Float32Array.from([3, 1, 5, NaN, 2, 4]);
const SCORES = Float32Array.from([3, 1, 5, 7, 2, 4]);         // total of the ranked points 15

test("the points are ranked by compared score, highest first, with the sum of their scores above each rank", () => {
  const ranked = rankScorePoints(COMPARED, SCORES);
  expect([...ranked.comparedDescending]).toEqual([5, 4, 3, 2, 1]);
  expect([...ranked.scoreAboveRank]).toEqual([0, 5, 9, 12, 14, 15]);
});

test("a cutoff keeps the points at or below it and carves the share of the score above it", () => {
  const ranked = rankScorePoints(COMPARED, SCORES);
  expect(keptShareAt(ranked, 3)).toBe(3 / 5);
  expect(carveAmountAt(ranked, 3)).toBe(9 / 15);
  expect(keptShareAt(ranked, 5)).toBe(1);
  expect(carveAmountAt(ranked, 5)).toBe(0);
  expect(keptShareAt(ranked, 0)).toBe(0);
  expect(carveAmountAt(ranked, 0)).toBe(1);
});

test("a carve amount gives the cutoff by the engine's rule: the first rank whose running sum passes the amount", () => {
  const ranked = rankScorePoints(COMPARED, SCORES);
  expect(cutoffForCarveAmount(ranked, 9 / 15)).toBe(3);         // 5 + 4 reach the amount, 3 would pass it: cut at 3
  expect(cutoffForCarveAmount(ranked, 0.5)).toBe(4);            // 7.5: 5 is below, 5 + 4 passes
  expect(cutoffForCarveAmount(ranked, 0)).toBe(5);              // nothing carved
  expect(cutoffForCarveAmount(ranked, 1)).toBe(1);              // everything but the lowest
  expect(carveAmountAt(ranked, cutoffForCarveAmount(ranked, 9 / 15)!)).toBe(9 / 15);
  expect(cutoffForCarveAmount(rankScorePoints(new Float32Array(0), new Float32Array(0)), 0.7)).toBeNull();
});

test("a cutoff is rounded to a hundredth of the highest score or less, a power of ten", () => {
  expect(cutoffStep(12350)).toBe(100);
  expect(cutoffStep(29.25)).toBe(0.1);
  expect(cutoffStep(0)).toBe(1);
  expect(roundedToStep(8348, 100)).toBe(8300);
  expect(roundedToStep(0.30000000000000004, 0.1)).toBe(0.3);
});
