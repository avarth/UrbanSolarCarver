import { expect, test } from "vitest";
import { gridIsOverBudget, smallestVoxelSizeWithinBudget } from "./grid_budget";

test("smallest voxel size that fits the budget", () => {
  expect(smallestVoxelSizeWithinBudget(1.0, 1_500_000_000, 500_000_000)).toBe(1.5);
  expect(smallestVoxelSizeWithinBudget(0.06, 690_807_104, 500_000_000)).toBe(0.07);   // 0.0668, to 0.01 m below 1 m
  expect(smallestVoxelSizeWithinBudget(1.0, 600_000_000, 500_000_000)).toBe(1.1);     // 1.0627, to 0.1 m from 1 m up
});

test("a size that lands on a step stays there despite floating point noise", () => {
  expect(smallestVoxelSizeWithinBudget(0.5, 8 * 500_000_000, 500_000_000)).toBe(1);     // 0.5 × 2
  expect(smallestVoxelSizeWithinBudget(0.1, 8 * 500_000_000, 500_000_000)).toBe(0.2);
});

test("a grid is over the budget only when it has more voxels than the budget", () => {
  expect(gridIsOverBudget({ resolution: 884, voxel_size: 0.06, total_voxels: 690_807_104, extent: 53, budget_voxels: 500_000_000 })).toBe(true);
  expect(gridIsOverBudget({ resolution: 62, voxel_size: 1, total_voxels: 238_328, extent: 62, budget_voxels: 500_000_000 })).toBe(false);
  expect(gridIsOverBudget(null)).toBe(false);
});
