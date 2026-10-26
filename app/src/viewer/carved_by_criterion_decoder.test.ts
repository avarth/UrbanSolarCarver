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

test("a header whose JSON is not a multiple of 4 bytes is padded, and the voxels still start where the padding ends", () => {
  // Ids of one to four digits change the JSON length by one byte each, so some of these need padding.
  const withPadding = ["1", "10", "100", "1000"].filter((id) => (JSON.stringify({ origin: [0, 0, 0], shape: [2, 1, 1], voxel_size: 1, criterion_ids: [id] }).length % 4) !== 0);
  expect(withPadding.length).toBeGreaterThan(0);
  for (const id of withPadding) {
    const buffer = packCarvedByCriterion([2, 1, 1], [id], [1, 0]);
    expect(new DataView(buffer).getUint32(0, true) % 4).toBe(0);
    const decoded = decodeCarvedByCriterion(buffer);
    expect(decoded.criterionIds).toEqual([id]);
    expect(Array.from(decoded.carvedBy)).toEqual([1, 0]);
  }
});

test("more carved voxels than the cap are thinned to every second, third, ... one in grid order, and the count before thinning is kept", () => {
  const decoded = decodeCarvedByCriterion(packCarvedByCriterion([6, 1, 1], ["1", "2"], [1, 0, 2, 2, 1, 1]));
  const thinned = carvedVoxelsByCriterion(decoded, [0, 0, 0], 3);
  expect(thinned.carvedCount).toBe(5);
  expect(thinned.thinningStep).toBe(2);
  expect(Array.from(thinned.criterionIndex)).toEqual([0, 1, 0]);                       // the 1st, 3rd and 5th carved voxels: flat 0, 3, 5
  expect(Array.from(thinned.centres.filter((_, position) => position % 3 === 0))).toEqual([0.5, 3.5, 5.5]);
  const whole = carvedVoxelsByCriterion(decoded, [0, 0, 0]);
  expect([whole.thinningStep, whole.criterionIndex.length]).toEqual([1, 5]);
});
