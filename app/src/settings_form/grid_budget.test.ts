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
  // 500³ voxels exactly at the budget is still within it, one voxel over is not (check_voxel_grid_budget refuses only a count above it)
  expect(gridIsOverBudget({ resolution: 500, voxel_size: 0.1, total_voxels: 125_000_000, extent: 50, budget_voxels: 125_000_000 })).toBe(false);
  expect(gridIsOverBudget({ resolution: 500, voxel_size: 0.1, total_voxels: 125_000_000, extent: 50, budget_voxels: 124_999_999 })).toBe(true);
  expect(gridIsOverBudget(null)).toBe(false);
});
