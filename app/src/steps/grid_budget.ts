// The voxel budget of the analysis (UX 5.4, 11): a grid with more voxels than preprocessing can score is refused, and the
// message names the smallest voxel size that fits. The grid is cubic, so the count goes with the cube of the voxel size.
import type { GridPlanReply } from "../api_client/client";

const FINE_STEP_METRES = 0.01;          // below 1 m
const COARSE_STEP_METRES = 0.1;         // from 1 m up
// The quotient of a size that lies on a step can come out a hair above the whole number (0.07 / 0.01 = 7.000000000000001);
// that hair must not round it up a whole step.
const ROUNDING_TOLERANCE = 1e-9;

export function gridIsOverBudget(gridPlan: GridPlanReply | null): boolean {
  return gridPlan !== null && gridPlan.total_voxels > gridPlan.budget_voxels;
}

/**
 * The current size times the cube root of count over budget, rounded up to 0.01 m below 1 m and to 0.1 m from 1 m up:
 * 0.06 m × 1.114 = 0.067 m gives 0.07 m; 1.06 m gives 1.1 m.
 */
export function smallestVoxelSizeWithinBudget(voxelSize: number, totalVoxels: number, budgetVoxels: number): number {
  const fittingSize = voxelSize * Math.cbrt(totalVoxels / budgetVoxels);
  const step = fittingSize < 1 ? FINE_STEP_METRES : COARSE_STEP_METRES;
  const stepsUp = Math.ceil(fittingSize / step - ROUNDING_TOLERANCE);
  return Number((stepsUp * step).toFixed(2));
}
