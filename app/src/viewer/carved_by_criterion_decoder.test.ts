import { expect, test } from "vitest";
import { carvedVoxelsByCriterion, decodeCarvedByCriterion } from "./carved_by_criterion_decoder";
import { packCarvedByCriterion } from "./packed_results_for_test";

test("decodes a carved-by-criterion buffer", () => {
  // shape (2, 2, 1): voxel 1 was removed by the first criterion on, voxel 2 by the second; 0 is kept or empty
  const decoded = decodeCarvedByCriterion(packCarvedByCriterion([2, 2, 1], ["1", "3"], [0, 1, 2, 0], [100, 200, 0], 0.5));
  expect(decoded.origin).toEqual([100, 200, 0]);
  expect(decoded.shape).toEqual([2, 2, 1]);
  expect(decoded.voxelSize).toBe(0.5);
  expect(decoded.criterionIds).toEqual(["1", "3"]);
  expect(Array.from(decoded.carvedBy)).toEqual([0, 1, 2, 0]);
});

test("the carved voxels come with their centres, shifted by the local origin, and the position of their criterion in the ids", () => {
  const decoded = decodeCarvedByCriterion(packCarvedByCriterion([2, 2, 1], ["1", "3"], [0, 1, 2, 0], [100, 200, 0], 0.5));
  const { centres, criterionIndex } = carvedVoxelsByCriterion(decoded, [99, 199, 0]);
  // flat index 1 is i = 0, j = 1; index 2 is i = 1, j = 0
  expect(Array.from(centres)).toEqual([1.25, 1.75, 0.25, 1.75, 1.25, 0.25]);
  expect(Array.from(criterionIndex)).toEqual([0, 1]);
});

test("a grid where nothing was carved has no carved voxels", () => {
  const decoded = decodeCarvedByCriterion(packCarvedByCriterion([1, 1, 2], ["1", "2"], [0, 0]));
  expect(carvedVoxelsByCriterion(decoded, [0, 0, 0]).criterionIndex).toHaveLength(0);
});
